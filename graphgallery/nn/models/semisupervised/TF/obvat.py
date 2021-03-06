import tensorflow as tf
from tensorflow.keras import Model, Input
from tensorflow.keras.layers import Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import regularizers
from tensorflow.keras.initializers import TruncatedNormal
from tensorflow.keras.losses import SparseCategoricalCrossentropy

from graphgallery.nn.layers import GraphConvolution, Gather
from graphgallery.nn.models import SemiSupervisedModel
from graphgallery.sequence import FullBatchNodeSequence
from graphgallery.utils.bvat_utils import kl_divergence_with_logit, entropy_y_x
from graphgallery.utils.decorators import EqualVarLength
from graphgallery import transformers as T


class OBVAT(SemiSupervisedModel):
    """
        Implementation of optimization-based Batch Virtual Adversarial Training 
        Graph Convolutional Networks (OBVAT).
        `Batch Virtual Adversarial Training for Graph Convolutional Networks 
        <https://arxiv.org/abs/1902.09192>`
        Tensorflow 1.x implementation: <https://github.com/thudzj/BVAT>

    """

    def __init__(self, *graph, adj_transformer="normalize_adj", attr_transformer=None,
                 device='cpu:0', seed=None, name=None, **kwargs):
        """Creat an optimization - based Batch Virtual Adversarial Training
        Graph Convolutional Networks(OBVAT) model.

        This can be instantiated in several ways:

            model = OBVAT(graph)
                with a `graphgallery.data.Graph` instance representing
                A sparse, attributed, labeled graph.

            model = OBVAT(adj_matrix, attr_matrix, labels)
                where `adj_matrix` is a 2D Scipy sparse matrix denoting the graph,
                 `attr_matrix` is a 2D Numpy array - like matrix denoting the node
                 attributes, `labels` is a 1D Numpy array denoting the node labels.

        Parameters:
        ----------
        graph: An instance of `graphgallery.data.Graph` or a tuple(list) of inputs.
            A sparse, attributed, labeled graph.
        adj_transformer: string, `transformer`, or None. optional
            How to transform the adjacency matrix. See `graphgallery.transformers`
            (default: : obj: `'normalize_adj'` with normalize rate `- 0.5`.
            i.e., math:: \hat{A} = D^{-\frac{1}{2}} A D^{-\frac{1}{2}})
        attr_transformer: string, transformer, or None. optional
            How to transform the node attribute matrix. See `graphgallery.transformers`
            (default: obj: `None`)
        device: string. optional
            The device where the model is running on. You can specified `CPU` or `GPU`
            for the model. (default:: str: `CPU: 0`, i.e., running on the 0-th `CPU`)
        seed: interger scalar. optional
            Used in combination with `tf.random.set_seed` & `np.random.seed`
            & `random.seed` to create a reproducible sequence of tensors across
            multiple calls. (default: obj: `None`, i.e., using random seed)
        name: string. optional
            Specified name for the model. (default: : str: `class.__name__`)
        kwargs: other customed keyword Parameters.
        """
        super().__init__(*graph, device=device, seed=seed, name=name, **kwargs)

        self.adj_transformer = T.get(adj_transformer)
        self.attr_transformer = T.get(attr_transformer)
        self.process()

    def process_step(self):
        graph = self.graph
        adj_matrix = self.adj_transformer(graph.adj_matrix)
        attr_matrix = self.attr_transformer(graph.attr_matrix)

        with tf.device(self.device):
            self.feature_inputs, self.structure_inputs = T.astensors(
                attr_matrix, adj_matrix)

    # use decorator to make sure all list arguments have the same length
    @EqualVarLength()
    def build(self, hiddens=[16], activations=['relu'], dropouts=[0.5],
              l2_norms=[5e-4], use_bias=False, lr=0.01, p1=1.4, p2=0.7):

        with tf.device(self.device):

            x = Input(batch_shape=[None, self.graph.n_attrs],
                      dtype=self.floatx, name='attr_matrix')
            adj = Input(batch_shape=[None, None],
                        dtype=self.floatx, sparse=True, name='adj_matrix')
            index = Input(batch_shape=[None],
                          dtype=self.intx, name='node_index')
            GCN_layers = []
            dropout_layers = []
            for hid, activation, dropout, l2_norm in zip(hiddens, activations, dropouts, l2_norms):
                GCN_layers.append(GraphConvolution(hid, activation=activation, use_bias=use_bias,
                                                   kernel_regularizer=regularizers.l2(l2_norm)))
                dropout_layers.append(Dropout(rate=dropout))

            GCN_layers.append(GraphConvolution(
                self.graph.n_classes, use_bias=use_bias))
            self.GCN_layers = GCN_layers
            self.dropout_layers = dropout_layers

            logit = self.forward(x, adj)
            output = Gather()([logit, index])

            model = Model(inputs=[x, adj, index], outputs=output)
            model.compile(loss=SparseCategoricalCrossentropy(from_logits=True),
                          optimizer=Adam(lr=lr), metrics=['accuracy'])

            self.r_vadv = tf.Variable(TruncatedNormal(stddev=0.01)(
                shape=[self.graph.n_nodes, self.graph.n_attrs]), name="r_vadv")
            entropy_loss = entropy_y_x(logit)
            vat_loss = self.virtual_adversarial_loss(x, adj, logit)
            model.add_loss(p1 * vat_loss + p2 * entropy_loss)

            self.model = model
            self.adv_optimizer = Adam(lr=lr / 10)

    def virtual_adversarial_loss(self, x, adj, logit):

        adv_x = x + self.r_vadv
        logit_p = tf.stop_gradient(logit)
        logit_m = self.forward(adv_x, adj)
        loss = kl_divergence_with_logit(logit_p, logit_m)
        return loss

    def forward(self, x, adj):
        h = x
        for dropout_layer, GCN_layer in zip(self.dropout_layers, self.GCN_layers[:-1]):
            h = dropout_layer(h)
            h = GCN_layer([h, adj])
        h = dropout_layer(h)
        h = self.GCN_layers[-1]([h, adj])
        return h

    @ tf.function
    def extra_train(self, epochs=10):

        with tf.device(self.device):
            r_vadv = self.r_vadv
            optimizer = self.adv_optimizer
            x, adj = self.feature_inputs, self.structure_inputs
            r_vadv.assign(TruncatedNormal(stddev=0.01)(shape=tf.shape(r_vadv)))
            for _ in range(epochs):
                with tf.GradientTape() as tape:
                    rnorm = tf.nn.l2_loss(r_vadv)
                    logit = self.forward(x, adj)
                    vloss = self.virtual_adversarial_loss(x, adj, logit)
                    loss = rnorm - vloss
                gradient = tape.gradient(loss, r_vadv)
                optimizer.apply_gradients(zip([gradient], [r_vadv]))

    def train_step(self, sequence):
        self.extra_train()
        return super().train_step(sequence)

    def train_sequence(self, index):
        index = T.asintarr(index)
        labels = self.graph.labels[index]
        with tf.device(self.device):
            sequence = FullBatchNodeSequence(
                [self.feature_inputs, self.structure_inputs, index], labels)
        return sequence
