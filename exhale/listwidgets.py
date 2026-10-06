#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 13 16:00:24 2025

@author: carl
"""

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt
import numpy as np

from .elementsettings import ElementSettings
from .imagesettings import ImageSettings
from .source_refs import ElementRef
from . import icons

class ExhaleListWidget(QtWidgets.QListWidget):
    "Base class for the lists below"
    itemUnwanted = QtCore.Signal(QtWidgets.QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)

    def keyPressEvent(self, event):
        if (event.matches(QtGui.QKeySequence.Delete) or
            event.matches(QtGui.QKeySequence.Backspace)):
            event.accept()
            if self.currentItem():
                self.itemUnwanted.emit(self.currentItem())
        else:
            super().keyPressEvent(event)


class ElementListWidget(ExhaleListWidget):
    "List of elements that can be selected, with ElementRef as data"
    ELEMENT_REF_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        # self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        # self.setDefaultDropAction(Qt.MoveAction)
        # self.setSortingEnabled(True)
        # self.setDragEnabled(True)
        # self.setAcceptDrops(True)
        # self.setDropIndicatorShown(True)

    # def dropEvent(self, event : QtGui.QDropEvent):
    #     if type(event.source()) == type(self):
    #         event.accept()
    #         print("drop OK")
    #         super().dropEvent(event)

    def addElementRef(self, name: str, ref: ElementRef, checked=False):
        "Add element via ElementRef."
        item = QtWidgets.QListWidgetItem(
            icons.icon(icons.IconName.ELEMENT), name)
        item.setData(self.ELEMENT_REF_ROLE, ref)
        item.setCheckState(Qt.CheckState.Checked if checked
                           else Qt.CheckState.Unchecked)
        self.addItem(item)

    def reload_icons(self):
        icon = icons.icon(icons.IconName.ELEMENT)
        for row in range(self.count()):
            self.item(row).setIcon(icon)


class ImageListWidget(ExhaleListWidget):
    "List of images with editable names and an integer as data"
    IMG_NUM_ROLE = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event : QtGui.QDropEvent):
        # event.mimeData().dumpObjectTree()
        # print("imglist drop")
        print(event.source())
        super().dropEvent(event)

    def addImage(self, num : int, imageSettings : ImageSettings):
        "Add image to this list by id and settings object"
        item = QtWidgets.QListWidgetItem(
            icons.icon(icons.IconName.IMAGE), imageSettings.name)
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

    def reload_icons(self):
        icon = icons.icon(icons.IconName.IMAGE)
        for row in range(self.count()):
            self.item(row).setIcon(icon)

class ColorButton(QtWidgets.QPushButton):
    "A blank button with a color and associated color picker"
    colorChanged = QtCore.Signal(list)    # RGB in [0-1]*3

    def __init__(self, text=" "):
        super().__init__(text)
        self.setMinimumWidth(15)
        self.setMaximumWidth(30)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Preferred)
        self.dialog = QtWidgets.QColorDialog()

        def picked():
            self.setColor(self.dialog.currentColor())
        def pick():
            self.dialog.open(picked)
        self.clicked.connect(pick)

    def color(self):
        # color = self.palette().color(0)
        color = self.palette().color(QtGui.QPalette.ColorRole.Button)
        return [color.redF(), color.greenF(), color.blueF()]

    def setColor(self, color):
        if isinstance(color, np.ndarray) or isinstance(color, list):
            color = QtGui.QColor.fromRgbF(*map(float, color))
        pal = self.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Button, color)
        self.setPalette(pal)
        # self.setPalette(QtGui.QPalette(color))
        self.dialog.setCurrentColor(color)
        self.colorChanged.emit(
            [color.redF(), color.greenF(), color.blueF()])

class ImageElementBoxBase(QtWidgets.QHBoxLayout):
    "Base class for a row of widgets describing an element in an image"
    colorChanged = QtCore.Signal(list)    # RGB in [0-1]*3

    def __init__(self, rgb):
        "Create common widgets but don't add them"
        super().__init__()
        # butt = QtWidgets.QPushButton(" ")
        # butt.setMinimumWidth(15)
        # butt.setMaximumWidth(30)
        # butt.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
        #                    QtWidgets.QSizePolicy.Policy.Preferred)
        # self.dialog = QtWidgets.QColorDialog()
        # def picked():
        #     self.setColor(self.dialog.currentColor())
        # def pick():
        #     self.dialog.open(picked)
        # butt.clicked.connect(pick)
        # self.colorButton = butt
        self.colorButton = ColorButton()
        self.colorButton.colorChanged.connect(self.colorChanged.emit)
        self.edit = QtWidgets.QPushButton("Show")
        self.edit.setCheckable(True)
        self.setColor(rgb)

    def setColor(self, color):
        self.colorButton.setColor(color)
        # if isinstance(color, np.ndarray):
        #     color = QtGui.QColor.fromRgbF(*map(float, color))
        # self.colorButton.setPalette(QtGui.QPalette(color))
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
        self.border = QtWidgets.QSpinBox()
        self.border.setRange(0, 30)
        self.addWidget(self.colorButton, 0)
        self.addWidget(QtWidgets.QLabel("Border"), 5)
        self.addWidget(self.border, 5)
        self.addWidget(self.edit, 0)

    def setWidgetsEnabled(self, enabled : bool):
        super().setWidgetsEnabled(enabled)
        self.border.setEnabled(enabled)

class ImageElementBox(ImageElementBoxBase):
    "A row of widgets describing an element in an image"
    def __init__(self, rgb):
        super().__init__(rgb)
        self.combo = QtWidgets.QComboBox()
        self.combo.addItem("(none)", userData=None)
        self.addWidget(self.colorButton, 0)
        self.addWidget(self.combo, 10)
        self.addWidget(self.edit, 0)

    def setWidgetsEnabled(self, enabled : bool):
        super().setWidgetsEnabled(enabled)
        self.combo.setEnabled(enabled)
