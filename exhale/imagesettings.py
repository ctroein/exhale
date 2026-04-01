#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug 15 19:07:15 2025

@author: carl
"""


import numpy as np
from enum import Enum

from .elementsettings import ElementSettings

class Layouts(Enum):
    "Ways of laying out images to be composed"
    MERGED = 0, "Merged only"
    IL = 1, "Images left"
    IR = 2, "Images right"
    IA = 3, "Images above"
    IB = 4, "Images below"
    # SQUARES = 5, "Four squares"

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

class Scalebars(Enum):
    "Predefined scale bar settings"
    NONE = 0, "None"
    LL = 1, "Lower left"
    LR = 2, "Lower right"
    UL = 3, "Upper left"
    UR = 4, "Upper right"

    def __new__(cls, *args, **kwds):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, _, description: str):
        self._description_ = description

    @property
    def description(self):
        return self._description_

class ImageSettings:
    "Settings for an image and its composition"
    MAX_ELEMENTS = 4

    def __init__(self, name : str):
        self.name = name
        self.layout = Layouts.IL
        self.scalebar = Scalebars.LL
        self.scalebarColor = [1.,1,0]
        self.scalebarBgColor = [0,0,0]
        self.scalebarBgAlpha = None
        self.fontsize = 11
        self.borderColor = np.zeros(3)
        self.borderWidth = 3
        self.panelLabels = True
        self.elementLabels = True
        self.colorscheme = Colorschemes.RGB
        self.customColors = None
        self.elements = {} # position -> ElementSettings
        self.dpi = 300
        self.clipColors = True # Hard clip of RGB or rescale by theor. max
        self.resolution = [200, "nm"]
        # self.pdfSize = [10., 10.]
        # self.pdfKeepDim = 0 # keep width(0) or height(1) when aspect changes
        # self._mergedImage = None

    def setLayout(self, l : Layouts):
        "Set layout type"
        if not isinstance(l, Layouts):
            raise ValueError(f"Expected Layouts, not {type(l)}")
        self.layout = l

    def setScalebar(self, sb : Scalebars):
        "Set scalebar position"
        if not isinstance(sb, Scalebars):
            raise ValueError(f"Expected Scalebars, not {type(sb)}")
        self.scalebar = sb

    def setColorscheme(self, cs : Colorschemes):
        "Set the colorscheme and possibly copy custom colors"
        if not isinstance(cs, Colorschemes):
            raise ValueError(f"Expected colorscheme, not {type(cs)}")
        self.colorscheme = cs
        if cs == Colorschemes.CUSTOM:
            self.customColors = cs.colors().copy()
        # TODO: Maybe len(elements) needs to be adjusted

    def setResolution(self, value: float, units: str):
        "Set the pixel resolution"
        if units not in ["cm", "mm", "µm", "um", "nm", "pm", "None"]:
            raise ValueError(f"Invalid length units '{units}'")
        if value <= 0:
            raise ValueError("Resolution must be > 0")
        self.resolution = [value, units]

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

    def setBorderWidth(self, width):
        self.borderWidth = width

    def setBorderColor(self, rgb):
        self.borderColor = rgb

    def setScalebarColors(self, color, bgcolor, bgalpha):
        # print("setcolors", color, bgcolor, bgalpha)
        self.scalebarColor = color
        self.scalebarBgColor = bgcolor
        self.scalebarBgAlpha = bgalpha

    def setFontsize(self, size):
        self.fontsize = size

    def setDPI(self, dpi):
        self.dpi = dpi

    def setLabels(self, panelLabels, elementLabels):
        self.panelLabels = panelLabels
        self.elementLabels = elementLabels


    # def dpi(self):
    #     "Compute dpi from selected size"
    #     return None

    # def aspect(self):
    #     "Compute aspect ratio, or None for unknown"
    #     return None

    # def setSize(self, wh, value):
    #     "Set the width or height; the other will be adjusted"
    #     self.pdfSize[wh] = value
    #     self.pdfKeepDim = wh
    #     asp = self.aspect()
    #     if asp is not None:
    #         self.pdfSize[1 - wh] = value * asp if wh else value / asp

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





