#!/usr/bin/env python3
"""Element, image, colour, and compact channel controls for the main window."""

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt

from .. import icons
from ..data.imagesettings import ImageSettings
from ..data.source_refs import ElementRef

_GROUP_DIVIDER_ROLE = Qt.UserRole + 13


class _ElementItemDelegate(QtWidgets.QStyledItemDelegate):
    """Expose the standard decoration geometry to the owning Python widget."""

    DIVIDER_HEIGHT = 5

    def _style_option(self, option, index):
        option = QtWidgets.QStyleOptionViewItem(option)
        if index.data(_GROUP_DIVIDER_ROLE):
            option.rect.adjust(0, self.DIVIDER_HEIGHT, 0, 0)
        return option

    def paint(self, painter, option, index):
        if index.data(_GROUP_DIVIDER_ROLE):
            painter.save()
            painter.setPen(option.palette.color(QtGui.QPalette.ColorRole.Mid))
            y = option.rect.top() + self.DIVIDER_HEIGHT // 2
            painter.drawLine(option.rect.left() + 4, y, option.rect.right() - 4, y)
            painter.restore()
        super().paint(painter, self._style_option(option, index), index)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(_GROUP_DIVIDER_ROLE):
            size.setHeight(size.height() + self.DIVIDER_HEIGHT)
        return size

    def decoration_rect(self, index, item_rect):
        view = self.parent()
        option = QtWidgets.QStyleOptionViewItem()
        self.initStyleOption(option, index)
        option.rect = item_rect
        option.widget = view
        option = self._style_option(option, index)
        if not option.decorationSize.isValid():
            size = view.style().pixelMetric(
                QtWidgets.QStyle.PixelMetric.PM_SmallIconSize,
                option,
                view,
            )
            option.decorationSize = QtCore.QSize(size, size)
        return view.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_ItemViewItemDecoration,
            option,
            view,
        )


class ExhaleListWidget(QtWidgets.QListWidget):
    "Base class for the lists below"

    itemUnwanted = QtCore.Signal(QtWidgets.QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.Delete) or event.matches(QtGui.QKeySequence.Backspace):
            event.accept()
            if self.currentItem():
                self.itemUnwanted.emit(self.currentItem())
        else:
            super().keyPressEvent(event)


class ElementListWidget(ExhaleListWidget):
    "List of elements that can be selected, with ElementRef as data"

    ELEMENT_REF_ROLE = Qt.UserRole + 1
    CHANNEL_KEY_ROLE = Qt.UserRole + 2
    SAMPLE_STATE_ROLE = Qt.UserRole + 10
    SAMPLE_DEFERRED_ROLE = Qt.UserRole + 11
    SAMPLE_PROJECT_ENABLED_ROLE = Qt.UserRole + 12
    stateToggleRequested = QtCore.Signal(QtWidgets.QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_ElementItemDelegate(self))
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._state_icon_press_item = None
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
        return self.addChannel(
            name,
            ref.item_id.rsplit("/", 1)[-1],
            ref,
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
        )

    def addChannel(self, name, key, ref, check_state, *, tristate=False):
        """Add a project or sample channel with its effective state."""
        item = QtWidgets.QListWidgetItem(icons.icon(icons.IconName.ELEMENT), name)
        item.setData(self.ELEMENT_REF_ROLE, ref)
        item.setData(self.CHANNEL_KEY_ROLE, key)
        item.setToolTip(f"Channel key: {key}")
        if tristate:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserTristate)
        item.setCheckState(check_state)
        self.addItem(item)
        return item

    def addSampleChannel(
        self,
        name,
        key,
        ref,
        state,
        *,
        deferred,
        project_enabled,
        group_divider=False,
    ):
        """Add a sample channel using the shared four-glyph state presentation."""
        item = QtWidgets.QListWidgetItem(name)
        item.setData(self.ELEMENT_REF_ROLE, ref)
        item.setData(self.CHANNEL_KEY_ROLE, key)
        item.setData(_GROUP_DIVIDER_ROLE, group_divider)
        self.updateSampleChannel(item, state, deferred=deferred, project_enabled=project_enabled)
        self.addItem(item)
        return item

    @staticmethod
    def updateSampleChannel(item, state, *, deferred, project_enabled):
        state_name = state.value if hasattr(state, "value") else str(state)
        active = state_name == "override" or (deferred and project_enabled)
        if deferred:
            icon_name = icons.IconName.MAP_PROJECT_YES if active else icons.IconName.MAP_PROJECT_NO
        else:
            icon_name = icons.IconName.MAP_YES if active else icons.IconName.MAP_NO
        item.setData(ElementListWidget.SAMPLE_STATE_ROLE, state_name)
        item.setData(ElementListWidget.SAMPLE_DEFERRED_ROLE, deferred)
        item.setData(ElementListWidget.SAMPLE_PROJECT_ENABLED_ROLE, project_enabled)
        item.setIcon(icons.icon(icon_name))
        item.setToolTip("")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentItem() is not None:
            if self.currentItem().data(self.SAMPLE_STATE_ROLE) is not None:
                event.accept()
                self.stateToggleRequested.emit(self.currentItem())
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self._state_icon_press_item = None
        position = event.pos()
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(position)
            if item is not None and item.data(self.SAMPLE_STATE_ROLE) is not None:
                if self._state_icon_rect(item).contains(position):
                    self._state_icon_press_item = item
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self._state_icon_press_item
        self._state_icon_press_item = None
        if (
            item is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self.itemAt(event.pos()) is item
            and self._state_icon_rect(item).contains(event.pos())
        ):
            event.accept()
            self.stateToggleRequested.emit(item)
            return
        super().mouseReleaseEvent(event)

    def _state_icon_rect(self, item):
        index = self.indexFromItem(item)
        return self.itemDelegate().decoration_rect(index, self.visualRect(index))

    def reload_icons(self):
        for row in range(self.count()):
            item = self.item(row)
            state = item.data(self.SAMPLE_STATE_ROLE)
            if state is None:
                item.setIcon(icons.icon(icons.IconName.ELEMENT))
            else:
                self.updateSampleChannel(
                    item,
                    state,
                    deferred=bool(item.data(self.SAMPLE_DEFERRED_ROLE)),
                    project_enabled=bool(item.data(self.SAMPLE_PROJECT_ENABLED_ROLE)),
                )


class ImageListWidget(ExhaleListWidget):
    "List of images with editable names and an integer as data"

    IMG_NUM_ROLE = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event: QtGui.QDropEvent):
        # event.mimeData().dumpObjectTree()
        # print("imglist drop")
        print(event.source())
        super().dropEvent(event)

    def addImage(self, num: int, imageSettings: ImageSettings):
        "Add image to this list by id and settings object"
        item = QtWidgets.QListWidgetItem(icons.icon(icons.IconName.IMAGE), imageSettings.name)
        item.setData(ImageListWidget.IMG_NUM_ROLE, num)
        item.setFlags(
            Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemNeverHasChildren
        )
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

    colorChanged = QtCore.Signal(list)  # RGB in [0-1]*3

    def __init__(self, text=" "):
        super().__init__(text)
        self.setMinimumWidth(15)
        self.setMaximumWidth(30)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred
        )
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
        self.colorChanged.emit([color.redF(), color.greenF(), color.blueF()])


class ImageElementBoxBase(QtWidgets.QHBoxLayout):
    "Base class for a row of widgets describing an element in an image"

    colorChanged = QtCore.Signal(list)  # RGB in [0-1]*3

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
        self.edit = QtWidgets.QPushButton("Adjust")
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

    def setWidgetsEnabled(self, enabled: bool):
        "Enable/disable all the widgets"
        self.colorButton.setEnabled(enabled)
        self.edit.setEnabled(enabled)


class ImageHeaderBox(ImageElementBoxBase):
    "A row of widgets for border color and 'show' button"

    def __init__(self, rgb=None):
        if rgb is None:
            rgb = np.zeros(3)
        super().__init__(rgb)
        self.border = QtWidgets.QSpinBox()
        self.border.setRange(0, 30)
        self.addWidget(self.colorButton, 0)
        self.addWidget(QtWidgets.QLabel("Border"), 5)
        self.addWidget(self.border, 5)
        self.addWidget(QtWidgets.QLabel("px"), 0)
        self.addStretch(10)
        self.edit.setText("Show image")

    def setWidgetsEnabled(self, enabled: bool):
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

    def setWidgetsEnabled(self, enabled: bool):
        super().setWidgetsEnabled(enabled)
        self.combo.setEnabled(enabled)
