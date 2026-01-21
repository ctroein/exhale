#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug  7 16:40:56 2025

@author: carl
"""

from enum import Enum
import h5py
from silx.gui.colors import Colormap
from scipy.stats import rankdata
import numpy as np

class Normalizers(Enum):
    "An Enum of the silx color normalizers, plus some of our own"
    LINEAR = 0, Colormap.LINEAR, "Linear"
    GAMMA = 1, Colormap.GAMMA, "Gamma"
    LOG = 2, Colormap.LOGARITHM, "Logarithmic"
    RANK = 3, "rank", "Rank"
    SQRT = 4, Colormap.SQRT, "Square root"
    ARCSINH = 5, Colormap.ARCSINH, "Arcsinh"

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    # ignore the first param since it's already set by __new__
    def __init__(self, _: str, cmname : str, description: str):
        self._cmname_ = cmname
        self._description_ = description

    # @property
    # def cmname(self):
    #     return self._cmname_

    @property
    def description(self):
        return self._description_

class ElementSettings():
    def __init__(self, h5 : h5py.Dataset):
        self._h5id = h5.id
        self.path = (h5.file.filename, h5.name)
        self.name = h5.name.rsplit('/', 1).pop()
        self.data = self.h5[()]
        self.dataRange = (self.data.min(), self.data.max())
        self.minPositive = self.data[self.data > 0].min()
        self.trfRange = list(self.dataRange)
        self.normalizer = Normalizers.LINEAR
        self.gamma = 1
        self.color = None

    def copy(self):
        e = type(self).__new__(self.__class__)
        e.__dict__.update(self.__dict__)
        e.trfRange = self.trfRange.copy()
        return e

    # def getColormap(self):
    #     "Get the current transformation as Colormap"
    #     return Colormap(normalization=self.normalizer.cmname)

    def getNormalizer(self):
        return self.normalizer.cmname

    def setMinmax(self, mm, val):
        "Set current min OR max from percentage"
        if not mm:
            self.trfRange[mm] = self.minConstraint(val, None)[0]
        else:
            self.trfRange[mm] = self.maxConstraint(val, None)[0]

    # def percent(self, mm):
    #     "Get current min/max as percentage"
    #     return (self.trfRange[mm] - self.dataRange[0]) / (
    #         self.dataRange[1] - self.dataRange[0]) * 100

    # def setPercent(self, mm, perc):
    #     "Set current min/max from percentage"
    #     val = self.dataRange[0] + .01 * perc * (
    #         self.dataRange[1] - self.dataRange[0])
    #     self.setMinmax(mm, val)

    def setMinmaxByMode(self, mode, param=None):
        modes = ['minmax', 'sd', 'percent']
        if mode not in modes:
            raise ValueError(f"mode must be one of {modes}")
        if mode == 'minmax':
            if self.normalizer == Normalizers.LOG:
                self.trfRange[0] = self.minPositive
            else:
                self.trfRange[0] = self.dataRange[0]
            self.trfRange[1] = self.dataRange[1]
            return

        if mode == 'sd':
            p = 3 if param is None else param
        else: # percent
            p = [5, 95] if param is None else param

        if self.normalizer == Normalizers.LOG:
            if mode == 'sd':
                data = np.log10(self.data[self.data > 0])
                m, sd = data.mean(), data.std()
                mm = 10 ** (m + p * np.array([-sd, sd]))
            else:
                mm = np.percentile(self.data[self.data > 0], p)
            self.trfRange[0] = max(self.minPositive, mm[0])
            self.trfRange[1] = min(self.dataRange[1], mm[1])
        else:
            if mode == 'sd':
                m, sd = self.data.mean(), self.data.std()
                mm = m + p * np.array([-sd, sd])
            else:
                mm = np.percentile(self.data, p)
            self.trfRange[0] = max(self.dataRange[0], mm[0])
            self.trfRange[1] = min(self.dataRange[1], mm[1])

    # @property
    # def h5Data(self):
    #     return self.h5[()]

    def transformedData(self):
        data = self.data
        vmin, vmax = self.trfRange

        if self.normalizer == Normalizers.ARCSINH:
            data = np.arcsinh((data - vmin) / (vmax - vmin))
            data[~np.isfinite(data)] = 0
            return data
        if self.normalizer == Normalizers.LOG:
            vmin = np.log10(vmin if vmin > 0 else self.minPositive)
            vmax = np.log10(vmax)
            with np.errstate(divide = 'ignore'):
                data = np.log10(data)
        elif self.normalizer == Normalizers.RANK:
            vmin = (data < vmin).sum() / (data.size - 1)
            vmax = (data < vmax).sum() / (data.size - 1)
            data = (rankdata(data) - 1).reshape(data.shape) / (data.size - 1)

        data = np.maximum(0., np.minimum(1., (data - vmin) / (vmax - vmin)))
        if self.normalizer == Normalizers.GAMMA:
            data = data ** self.gamma
        elif self.normalizer == Normalizers.SQRT:
            data = np.sqrt(data)

        data[~np.isfinite(data)] = 0
        # print("trf", data.min(), data.max(), self.normalizer.description, vmin, vmax)
        return data

    @property
    def h5(self):
        "Get the hdf5 object or possibly None if it's been unloaded"
        try:
            return h5py.Dataset(self._h5id)
        except:
            return None

    def minConstraint(self, x, y):
        return max(self.dataRange[0], min(self.trfRange[1], x)), y
    def maxConstraint(self, x, y):
        return min(self.dataRange[1], max(self.trfRange[0], x)), y

