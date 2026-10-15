#!/usr/bin/env python3
"""Composition settings, layouts, colours, and channel overrides for images."""

from copy import deepcopy
from enum import Enum

import numpy as np

from .constants import DISPLAY_UNITS
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


_COLORSCHEME_COLORS = np.array(
    [
        [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0.7, 0.7, 0.7]],
        [[0, 1, 1], [1, 0, 1], [1, 1, 0], [0.7, 0.7, 0.7]],
        [[1, 0.5, 0], [0, 1, 0.5], [0.5, 0, 1], [0.5, 0.5, 0.5]],
    ]
)


class Colorschemes(Enum):
    "Predefined color schemes"

    RGB = 0, "RGB"
    CMY = 1, "CMY"
    CUSTOM = 2, "Custom"

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
        return _COLORSCHEME_COLORS[self.value]

    def update(self, rgb):
        "Update a (presumably custom) colorscheme"
        _COLORSCHEME_COLORS[self.value] = rgb


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
    PRESENTATION_FIELDS = (
        "layout",
        "scalebar",
        "scalebarColor",
        "scalebarBgColor",
        "scalebarBgAlpha",
        "fontsize",
        "borderColor",
        "borderWidth",
        "panelLabels",
        "panelLabelColor",
        "elementLabels",
        "elementBorders",
        "elementLabelsColored",
        "colorscheme",
        "customColors",
        "dpi",
        "clipColors",
    )

    def __init__(self, name: str, *, sample_id=None, sample_source_ids=()):
        self.name = name
        self.sample_id = sample_id
        self.sample_source_ids = tuple(sample_source_ids)
        self.layout = Layouts.IL
        self.scalebar = Scalebars.LL
        self.scalebarColor = [1.0, 1.0, 0.0]
        self.scalebarBgColor = [0.0, 0.0, 0.0]
        self.scalebarBgAlpha = None
        self.fontsize = 11
        self.borderColor = np.zeros(3)
        self.borderWidth = 9
        self.panelLabels = True
        self.panelLabelColor = [1.0, 1.0, 1.0]
        self.elementLabels = True
        self.elementBorders = True
        self.elementLabelsColored = False
        self.colorscheme = Colorschemes.RGB
        self.customColors = None
        self.elements = {}  # position -> ElementSettings
        self.channel_keys = {}  # position -> sample channel key
        self.element_overrides = set()  # positions with image-local settings
        self.suspended_elements = {}  # position -> (ElementSettings, channel key, local override)
        self.dpi = 300
        self.clipColors = True  # Hard clip of RGB or rescale by theor. max
        self.resolution = [200, "nm"]
        # self.pdfSize = [10., 10.]
        # self.pdfKeepDim = 0 # keep width(0) or height(1) when aspect changes

    def copyForSample(self, name, sample_id, source_ids):
        "Return an empty image initialized from these composition settings."
        image = deepcopy(self)
        image.name = name
        image.sample_id = sample_id
        image.sample_source_ids = tuple(source_ids)
        image.elements = {}
        image.channel_keys = {}
        image.element_overrides = set()
        image.suspended_elements = {}
        return image

    def applyPresentationFrom(self, source):
        """Copy image presentation settings without identity, elements, or resolution."""
        for field in self.PRESENTATION_FIELDS:
            setattr(self, field, deepcopy(getattr(source, field)))

    def setLayout(self, layout: Layouts):
        "Set layout type"
        if not isinstance(layout, Layouts):
            raise ValueError(f"Expected Layouts, not {type(layout)}")
        self.layout = layout

    def setScalebar(self, sb: Scalebars):
        "Set scalebar position"
        if not isinstance(sb, Scalebars):
            raise ValueError(f"Expected Scalebars, not {type(sb)}")
        self.scalebar = sb

    def setColorscheme(self, cs: Colorschemes):
        "Set the colorscheme and possibly copy custom colors"
        if not isinstance(cs, Colorschemes):
            raise ValueError(f"Expected colorscheme, not {type(cs)}")
        self.colorscheme = cs
        if cs == Colorschemes.CUSTOM:
            self.customColors = cs.colors().copy()
        # TODO: Maybe len(elements) needs to be adjusted

    def setResolution(self, value: float, units: str):
        "Set the pixel resolution"
        if units not in DISPLAY_UNITS:
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
        self.scalebarColor = color
        self.scalebarBgColor = bgcolor
        self.scalebarBgAlpha = bgalpha

    def setPanelLabelColor(self, color):
        self.panelLabelColor = color

    def setFontsize(self, size):
        self.fontsize = size

    def setDPI(self, dpi):
        self.dpi = dpi

    def setLabels(self, panelLabels, elementLabels):
        self.panelLabels = panelLabels
        self.elementLabels = elementLabels

    def setElementLabelsColored(self, elc):
        self.elementLabelsColored = elc

    def setElementBorders(self, eb):
        self.elementBorders = eb

    # def dpi(self):
    #     "Compute dpi from selected size"
    #     return None

    def setElement(self, index: int, element: ElementSettings, channel_key=None):
        "Select a sample element for an image slot."
        if index < 0 or index >= self.MAX_ELEMENTS:
            raise ValueError(f"Element index must be between {0} and {self.MAX_ELEMENTS - 1}")
        self.suspended_elements.pop(index, None)
        if element is None:
            self.elements.pop(index, None)
            self.channel_keys.pop(index, None)
            self.element_overrides.discard(index)
        else:
            self.elements[index] = element
            self.channel_keys[index] = channel_key
            self.element_overrides.discard(index)

    def reconcileChannels(self, available_keys):
        """Suspend unavailable slots and restore unedited slots that become available."""
        available_keys = set(available_keys)
        changed = False
        for slot in list(self.elements):
            key = self.channel_keys[slot]
            if key in available_keys:
                continue
            self.suspended_elements[slot] = (
                self.elements.pop(slot),
                self.channel_keys.pop(slot),
                slot in self.element_overrides,
            )
            self.element_overrides.discard(slot)
            changed = True

        for slot, (element, key, overridden) in list(self.suspended_elements.items()):
            if key not in available_keys:
                continue
            if slot not in self.elements:
                self.elements[slot] = element
                self.channel_keys[slot] = key
                if overridden:
                    self.element_overrides.add(slot)
                changed = True
            del self.suspended_elements[slot]
        return changed

    def createElementOverride(self, index: int):
        "Create and return image-local settings for a selected slot."
        if index not in self.elements:
            raise KeyError(index)
        if index not in self.element_overrides:
            self.elements[index] = self.elements[index].copy()
            self.element_overrides.add(index)
        return self.elements[index]

    def revertElementOverride(self, index: int, element: ElementSettings):
        "Use sample settings again for an overridden slot."
        if index not in self.elements:
            raise KeyError(index)
        self.elements[index] = element
        self.element_overrides.discard(index)
