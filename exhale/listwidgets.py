#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 13 16:00:24 2025

@author: carl
"""

from silx.gui import qt
from silx.gui.qt import Qt
import silx.gui.colors
from h5py import Dataset
import numpy as np

from .elementsettings import ElementSettings
from .imagesettings import ImageSettings

class ExhaleListWidget(qt.QListWidget):
    "Base class for the lists below"
    itemUnwanted = qt.Signal(qt.QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)

    def keyPressEvent(self, event):
        if (event.matches(qt.QKeySequence.Delete) or
            event.matches(qt.QKeySequence.Backspace)):
            event.accept()
            if self.currentItem():
                self.itemUnwanted.emit(self.currentItem())
        else:
            super().keyPressEvent(event)


class ElementListWidget(ExhaleListWidget):
    "List of elements that can be selected, with h5 path as data"
    H5_PATH_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            qt.QAbstractItemView.SelectionMode.SingleSelection)
        # self.setDragDropMode(qt.QAbstractItemView.DragDropMode.DragDrop)
        # self.setDefaultDropAction(Qt.MoveAction)
        # self.setSortingEnabled(True)
        # self.setDragEnabled(True)
        # self.setAcceptDrops(True)
        # self.setDropIndicatorShown(True)

    # def dropEvent(self, event : qt.QDropEvent):
    #     if type(event.source()) == type(self):
    #         event.accept()
    #         print("drop OK")
    #         super().dropEvent(event)

    def addElement(self, name : str, dataset : Dataset, checked=False):
        item = qt.QListWidgetItem(
            qt.QIcon.fromTheme("applications-education-science"), name)
        path = (dataset.file.filename, dataset.name)
        item.setData(self.H5_PATH_ROLE, path)
        item.setCheckState(Qt.CheckState.Checked if checked
                           else Qt.CheckState.Unchecked)
        self.addItem(item)

    # def addElementFromSettings(self, element : ElementSettings):
    #     self.addElement(element.name, element.h5)


class ImageListWidget(ExhaleListWidget):
    "List of images with editable names and an integer as data"
    IMG_NUM_ROLE = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            qt.QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(qt.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event : qt.QDropEvent):
        # event.mimeData().dumpObjectTree()
        # print("imglist drop")
        print(event.source())
        super().dropEvent(event)

    def addImage(self, num : int, imageSettings : ImageSettings):
        "Add image to this list by id and settings object"
        item = qt.QListWidgetItem(
            qt.QIcon.fromTheme("view-list-icons"), imageSettings.name)
        item.setData(ImageListWidget.IMG_NUM_ROLE, num)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable |
                      Qt.ItemFlag.ItemIsEditable |
                      Qt.ItemFlag.ItemIsDragEnabled |
                      Qt.ItemFlag.ItemIsEnabled |
                      Qt.ItemFlag.ItemNeverHasChildren)
        # This is supposed to add the item at the bottom of the list but
        # for me it's usually (but not always) added at the top. Weird.
        self.addItem(item)
        self.setCurrentItem(item)

class ColorButton(qt.QPushButton):
    "A blank button with a color and associated color picker"
    colorChanged = qt.Signal(list)    # RGB in [0-1]*3

    def __init__(self, text=" "):
        super().__init__(text)
        self.setMinimumWidth(15)
        self.setMaximumWidth(30)
        self.setSizePolicy(qt.QSizePolicy.Policy.Preferred,
                           qt.QSizePolicy.Policy.Preferred)
        self.dialog = qt.QColorDialog()

        def picked():
            self.setColor(self.dialog.currentColor())
        def pick():
            self.dialog.open(picked)
        self.clicked.connect(pick)

    def color(self):
        # color = self.palette().color(0)
        color = self.palette().color(qt.QPalette.ColorRole.Button)
        return [color.redF(), color.greenF(), color.blueF()]

    def setColor(self, color):
        if isinstance(color, np.ndarray) or isinstance(color, list):
            color = silx.gui.colors.asQColor(color)
        pal = self.palette()
        pal.setColor(qt.QPalette.ColorRole.Button, color)
        self.setPalette(pal)
        # self.setPalette(qt.QPalette(color))
        self.dialog.setCurrentColor(color)
        self.colorChanged.emit(
            [color.redF(), color.greenF(), color.blueF()])

class ImageElementBoxBase(qt.QHBoxLayout):
    "Base class for a row of widgets describing an element in an image"
    colorChanged = qt.Signal(list)    # RGB in [0-1]*3

    def __init__(self, rgb):
        "Create common widgets but don't add them"
        super().__init__()
        # butt = qt.QPushButton(" ")
        # butt.setMinimumWidth(15)
        # butt.setMaximumWidth(30)
        # butt.setSizePolicy(qt.QSizePolicy.Policy.Preferred,
        #                    qt.QSizePolicy.Policy.Preferred)
        # self.dialog = qt.QColorDialog()
        # def picked():
        #     self.setColor(self.dialog.currentColor())
        # def pick():
        #     self.dialog.open(picked)
        # butt.clicked.connect(pick)
        # self.colorButton = butt
        self.colorButton = ColorButton()
        self.colorButton.colorChanged.connect(self.colorChanged.emit)
        self.edit = qt.QPushButton("Show")
        self.edit.setCheckable(True)
        self.setColor(rgb)

    def setColor(self, color):
        self.colorButton.setColor(color)
        # if isinstance(color, np.ndarray):
        #     color = silx.gui.colors.asQColor(color)
        # self.colorButton.setPalette(qt.QPalette(color))
        # self.dialog.setCurrentColor(color)
        # self.colorChanged.emit(
        #     [color.redF(), color.greenF(), color.blueF()])

    def setWidgetsEnabled(self, enabled : bool):
        "Enable/disable all the widgets"
        self.colorButton.setEnabled(enabled)
        self.edit.setEnabled(enabled)

class ImageHeaderBox(ImageElementBoxBase):
    "A row of widgets for border color and 'show' button"
    def __init__(self, rgb=np.zeros(3)):
        super().__init__(rgb)
        self.border = qt.QSpinBox()
        self.border.setRange(0, 30)
        self.addWidget(self.colorButton, 0)
        self.addWidget(qt.QLabel("Border"), 5)
        self.addWidget(self.border, 5)
        self.addWidget(self.edit, 0)

    def setWidgetsEnabled(self, enabled : bool):
        super().setWidgetsEnabled(enabled)
        self.border.setEnabled(enabled)

class ImageElementBox(ImageElementBoxBase):
    "A row of widgets describing an element in an image"
    def __init__(self, rgb):
        super().__init__(rgb)
        self.combo = qt.QComboBox()
        self.combo.addItem("(none)", userData=None)
        self.addWidget(self.colorButton, 0)
        self.addWidget(self.combo, 10)
        self.addWidget(self.edit, 0)

    def setWidgetsEnabled(self, enabled : bool):
        super().setWidgetsEnabled(enabled)
        self.combo.setEnabled(enabled)

