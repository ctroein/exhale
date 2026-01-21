#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 15 19:07:15 2025

@author: carl
"""


import numpy as np
from enum import Enum

from .element import ElementSettings

class Layouts(Enum):
    "Ways of laying out images to be composed"
    MERGED = 0, "Merged only"
    LEFT = 1, "Images left"
    TOP = 2, "Images above"
    SQUARES = 3, "Four squares"

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    # ignore the first param since it's already set by __new__
    def __init__(self, _, description: str):
        self._description_ = description

    @property
    def description(self):
        return self._description_

class Colorschemes(Enum):
    "Predefined color schemes"
    RGB = 0, "RGB"
    CMY = 1, "CMY"
    CUSTOM = 2, "Custom"

    __colors = np.array([
        [[1,0,0],[0,1,0],[0,0,1],[.7,.7,.7]],
        [[0,1,1],[1,0,1],[1,1,0],[.7,.7,.7]],
        [[1,.5,0],[0,1,.5],[.5,0,1],[.5,.5,.5]]
        ])

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    # ignore the first param since it's already set by __new__
    def __init__(self, _, description: str):
        self._description_ = description

    @property
    def description(self):
        return self._description_

    def colors(self):
        "Get rgb values"
        return self.__colors[self.value]

    def update(self, rgb):
        "Update a (presumably custom) colorscheme"
        self.__colors[self.value] = rgb

class ImageSettings:
    "Settings for an image and its composition"
    MAX_ELEMENTS = 4

    def __init__(self, name : str):
        self.name = name
        self.layout = Layouts.LEFT
        self.colorscheme = Colorschemes.RGB
        self.customColors = None
        self.elements = {} # position -> ElementSettings
        self.pdfSize = [10., 10.]
        self.pdfKeepDim = 0 # keep width(0) or height(1) when aspect changes
        self._mergedImage = None

    def setColorscheme(self, cs : Colorschemes):
        "Set the colorscheme and possibly copy custom colors"
        if not isinstance(cs, Colorschemes):
            raise ValueError(f"Expected colorscheme, not {type(cs)}")
        self.colorscheme = cs
        if cs == Colorschemes.CUSTOM:
            self.customColors = cs.colors().copy()
        # TODO: Maybe len(elements) needs to be adjusted

    def colors(self):
        if self.colorscheme == Colorschemes.CUSTOM:
            return self.customColors
        else:
            return self.colorscheme.colors()

    def setColor(self, num, rgb):
        ncols = len(self.colorscheme.colors())
        if num < 0 or num >= ncols:
            raise ValueError(f"Color index must be between {0} and {ncols}")
        if self.customColors is None:
            self.customColors = self.colorscheme.colors().copy()
        self.colorscheme = Colorschemes.CUSTOM
        self.customColors[num] = rgb
        self.colorscheme.update(self.customColors)

    def dpi(self):
        "Compute dpi from selected size"
        return None

    def aspect(self):
        "Compute aspect ratio, or None for unknown"
        return None

    def setSize(self, wh, value):
        "Set the width or height; the other will be adjusted"
        self.pdfSize[wh] = value
        self.pdfKeepDim = wh
        asp = self.aspect()
        if asp is not None:
            self.pdfSize[1 - wh] = value * asp if wh else value / asp

    def setElement(self, index : int, element : ElementSettings):
        "Copy an element into this image"
        if index < 0 or index >= self.MAX_ELEMENTS:
            raise ValueError("Element index must be between "
                             f"{0} and {self.MAX_ELEMENTS - 1}")
        if element is None:
            del self.elements[index]
        else:
            # Shallow copy; no need to copy the transformed data etc.
            self.elements[index] = element.copy()

    def mergedImage(self):
        "Update/return the composed image; merge the element images"
        if not self.elements:
            self._mergedImage = None
            return self._mergedImage
        shapes = np.array([es.data.shape for es in self.elements.values()])
        shape = np.max(shapes, axis=0)
        merged = np.zeros(list(shape) + [3])
        colors = self.colorscheme.colors()
        maxcolor = colors[list(self.elements.keys())].sum(0)
        maxcolor[maxcolor <= 0] = 1
        print("maxcolor", maxcolor)
        for i, es in self.elements.items():
            td = es.transformedData()
            h, w = td.shape
            merged[:h, :w] = merged[:h, :w] + td[..., None] * colors[i]
        if True:
            self._mergedImage = np.minimum(merged, 1.)
        else:
            self._mergedImage = merged / maxcolor
        return self._mergedImage
