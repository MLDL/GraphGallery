import tensorflow as tf
from tensorflow.keras import Model, Input
from tensorflow.keras.layers import Dropout
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import regularizers
from tensorflow.keras.losses import SparseCategoricalCrossentropy

from graphgallery.nn.layers import GraphConvAttribute, Gather
from graphgallery.nn.models import GCN
from graphgallery.utils.decorators import EqualVarLength


class GCNA(GCN):
    """
    GCN + attribute matrix

    Implementation of Graph Convolutional Networks(GCN) concated with attribute matrix.
    `Semi - Supervised Classification with Graph Convolutional Networks 
    <https://arxiv.org/abs/1609.02907>`
    GCN Tensorflow 1.x implementation: <https://github.com/tkipf/gcn>
    GCN Pytorch implementation: <https://github.com/tkipf/pygcn>

    """

    def __init__(self, *graph, adj_transformer="normalize_adj", attr_transformer=None,
                 device='cpu:0', seed=None, name=None, **kwargs):
        """Creat a Graph Convolutional Networks(GCN) model 
            concated with attribute matrix (GCNA).

        This can be instantiated in several ways:

            model = GCNA(graph)
                with a `graphgallery.data.Graph` instance representing
                A sparse, attributed, labeled graph.

            model = GCNA(adj_matrix, attr_matrix, labels)
                where `adj_matrix` is a 2D Scipy sparse matrix denoting the graph,
                 `attr_matrix` is a 2D Numpy array - like matrix denoting the node
                 attributes, `labels` is a 1D Numpy array denoting the node labels.

        Parameters:
        ----------
        graph: An instance of `graphgallery.data.Graph` or a tuple(list) of inputs.
            A sparse, attributed, labeled graph.
        adj_transformer: string, `transformer`, or None. optional
            How to transform the adjacency matrix. See `graphgallery.transformers`
            (default:: obj: `'normalize_adj'` with normalize rate `- 0.5`.
            i.e., math: : \hat{A} = D^{-\frac{1}{2}} A D^{-\frac{1}{2}})
        attr_transformer: string, transformer, or None. optional
            How to transform the node attribute matrix. See `graphgallery.transformers`
            (default: obj: `None`)
        device: string. optional
            The device where the model is running on. You can specified `CPU` or `GPU`
            for the model. (default: : str: `CPU: 0`, i.e., running on the 0-th `CPU`)
        seed: interger scalar. optional
            Used in combination with `tf.random.set_seed` & `np.random.seed`
            & `random.seed` to create a reproducible sequence of tensors across
            multiple calls. (default: obj: `None`, i.e., using random seed)
        name: string. optional
            Specified name for the model. (default:: str: `class.__name__`)
        kwargs: other customed keyword Parameters.
        """
        super().__init__(*graph,
                         adj_transformer=adj_transformer, attr_transformer=attr_transformer,
                         device=device, seed=seed, name=name, **kwargs)

    # use decorator to make sure all list arguments have the same length
    @EqualVarLength()
    def build(self, hiddens=[16], activations=['relu'], dropouts=[0.5],
              l2_norms=[5e-4], lr=0.01, use_bias=False):

        with tf.device(self.device):

            x = Input(batch_shape=[None, self.graph.n_attrs],
                      dtype=self.floatx, name='attr_matrix')
            adj = Input(
                batch_shape=[None, None], dtype=self.floatx, sparse=True, name='adj_matrix')
            index = Input(batch_shape=[None],
                          dtype=self.intx, name='node_index')

            h = x
            for hid, activation, dropout, l2_norm in zip(hiddens, activations, dropouts, l2_norms):
                h = GraphConvAttribute(hid, use_bias=use_bias,
                                       activation=activation,
                                       kernel_regularizer=regularizers.l2(l2_norm))([h, adj])

                h = Dropout(rate=dropout)(h)

            h = GraphConvAttribute(self.graph.n_classes,
                                   use_bias=use_bias)([h, adj])
            h = Gather()([h, index])

            model = Model(inputs=[x, adj, index], outputs=h)
            model.compile(loss=SparseCategoricalCrossentropy(from_logits=True),
                          optimizer=Adam(lr=lr), metrics=['accuracy'])

            self.model = model
