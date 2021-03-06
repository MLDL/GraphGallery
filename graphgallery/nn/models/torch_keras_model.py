import torch
import numpy as np
import torch.nn as nn

from torch.nn import Module
from torch import optim
from torch.autograd import Variable

from collections import OrderedDict
from graphgallery.utils import save


class TorchKerasModel(Module):
    """Keras like PyTorch Model"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # To be compatible with TensorFlow
        self._in_multi_worker_mode = dummy_function
        self._is_graph_network = dummy_function

    def build(self, inputs):
        ...

    def compile(self):
        ...
        
    def summary(self):
        ...

    def save_weights(self, filepath, overwrite=True, save_format=None):
        save.save_torch_weights(self, filepath, overwrite=overwrite, save_format=save_format)

    def save(self, filepath, overwrite=True, save_format=None, **kwargs):
        save.save_torch_model(self, filepath, overwrite=overwrite, save_format=save_format, **kwargs)


def dummy_function(*args, **kwargs):
    ...
