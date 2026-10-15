"""Controls for layers displayed in the embedded Napari viewer."""

from qtpy import QtCore, QtGui, QtWidgets

from .. import icons
from ..widgets import IconToolButton


def _with_brightness(color, level):
    return QtGui.QColor.fromRgbF(
        color.redF() * level,
        color.greenF() * level,
        color.blueF() * level,
        color.alphaF(),
    )


class LayerColorButton(QtWidgets.QToolButton):
    """A compact color or palette preview button."""

    modeSelected = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = [QtGui.QColor("white")]
        extent = self.fontMetrics().height() + 6
        self.setFixedSize(extent, extent)

    def set_colors(self, colors):
        self._colors = [QtGui.QColor(color) for color in colors]
        self.update()

    @staticmethod
    def _paint_colors(painter, rect, colors, outline=False):
        if len(colors) == 1:
            painter.fillRect(rect, colors[0])
        else:
            half_width = rect.width() // 2
            half_height = rect.height() // 2
            cells = (
                QtCore.QRect(rect.left(), rect.top(), half_width, half_height),
                QtCore.QRect(
                    rect.left() + half_width, rect.top(), rect.width() - half_width, half_height
                ),
                QtCore.QRect(
                    rect.left(), rect.top() + half_height, half_width, rect.height() - half_height
                ),
                QtCore.QRect(
                    rect.left() + half_width,
                    rect.top() + half_height,
                    rect.width() - half_width,
                    rect.height() - half_height,
                ),
            )
            for cell, color in zip(cells, colors, strict=True):
                painter.fillRect(cell, color)
        if outline:
            painter.setPen(QtGui.QColor(80, 80, 80))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    @classmethod
    def _preview_icon(cls, colors):
        pixmap = QtGui.QPixmap(20, 20)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        cls._paint_colors(
            painter,
            QtCore.QRect(1, 1, 18, 18),
            [QtGui.QColor(color) for color in colors],
            outline=True,
        )
        painter.end()
        return QtGui.QIcon(pixmap)

    def set_mode_options(self, options):
        "Set label display modes as previewed dropdown actions."
        old_menu = self.menu()
        menu = QtWidgets.QMenu(self)
        for mode, text, colors in options:
            action = menu.addAction(self._preview_icon(colors), text)
            action.setData(mode)
        menu.triggered.connect(lambda action: self.modeSelected.emit(action.data()))
        self.setMenu(menu)
        self.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        menu_width = self.style().pixelMetric(QtWidgets.QStyle.PM_MenuButtonIndicator)
        self.setFixedWidth(self.height() + menu_width)
        if old_menu is not None:
            old_menu.deleteLater()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        rect = self.style().subControlRect(
            QtWidgets.QStyle.CC_ToolButton,
            option,
            QtWidgets.QStyle.SC_ToolButton,
            self,
        )
        frame = self.style().pixelMetric(QtWidgets.QStyle.PM_DefaultFrameWidth, option, self)
        self._paint_colors(painter, rect.adjusted(frame, frame, -frame, -frame), self._colors)


class _DragHandle(QtWidgets.QLabel):
    def __init__(self, row):
        super().__init__("≡", row)
        self.row = row
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.setToolTip("Drag to reorder")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.row.layer_list.setCurrentItem(self.row.item)
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self.row.layer_list.startDrag(QtCore.Qt.MoveAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(QtCore.Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class LayerRowWidget(QtWidgets.QWidget):
    """Compact layer controls with details shown for the selected row."""

    def __init__(self, layer_list, item, layer):
        super().__init__(layer_list)
        from napari.layers import Labels

        self.layer_list = layer_list
        self.item = item
        self.layer = layer
        self.helper = layer_list.helper
        self.is_labels = isinstance(layer, Labels)
        self._color_dialog = QtWidgets.QColorDialog(self)

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(2, 2, 2, 2)
        outer_layout.setSpacing(2)
        layout = QtWidgets.QHBoxLayout()
        outer_layout.addLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.drag_handle = _DragHandle(self)
        layout.addWidget(self.drag_handle)
        self.visible = QtWidgets.QCheckBox()
        self.visible.setChecked(layer.visible)
        self.visible.setToolTip("Show layer")
        self.visible.toggled.connect(self._set_visible)
        layout.addWidget(self.visible)
        self.name_label = QtWidgets.QLabel(layer.name)
        self.name_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        layout.addWidget(self.name_label, 1)

        self.color_button = LayerColorButton()
        self.color_button.clicked.connect(self._pick_color)
        self.color_button.modeSelected.connect(self._set_label_mode)
        color_cell = QtWidgets.QWidget()
        color_layout = QtWidgets.QHBoxLayout(color_cell)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(0)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch(1)
        color_cell.setFixedWidth(layer_list.color_width)
        layout.addWidget(color_cell)

        self.opacity = QtWidgets.QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSingleStep(10)
        self.opacity.setSuffix("%")
        self.opacity.setValue(round(layer.opacity * 100))
        self.opacity.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.opacity.setToolTip("Opacity")
        self.opacity.setFixedWidth(layer_list.opacity_width)
        self.opacity.valueChanged.connect(self._set_opacity)
        layout.addWidget(self.opacity)

        self.additive = IconToolButton()
        self.additive.setCheckable(True)
        self.additive.setChecked(layer.blending == self.helper.BLENDING_ADD)
        self.additive.setToolTip("Additive blending")
        self.additive.setFixedWidth(layer_list.blend_width)
        self.additive.toggled.connect(self._set_blending)
        self._update_blending_icon()
        layout.addWidget(self.additive, 0, QtCore.Qt.AlignCenter)

        self.gain_row = QtWidgets.QWidget()
        gain_layout = QtWidgets.QHBoxLayout(self.gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.setSpacing(4)
        gain_layout.addStretch(1)
        gain_layout.addWidget(QtWidgets.QLabel("Gain"))
        self.gain = QtWidgets.QDoubleSpinBox()
        self.gain.setRange(1.0, 10.0)
        self.gain.setSingleStep(0.2)
        self.gain.setDecimals(1)
        self.gain.setSuffix("×")
        self.gain.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.gain.setValue(
            self.helper.layer_gain(layer) if self.helper.layer_has_gain(layer) else 1.0
        )
        self.gain.valueChanged.connect(self._set_gain)
        gain_layout.addWidget(self.gain)
        outer_layout.addWidget(self.gain_row)
        self.gain_row.setVisible(False)

        self._refresh_previews()

    def mousePressEvent(self, event):
        self.layer_list.setCurrentItem(self.item)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.visible.toggle()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _activate(self):
        self.layer_list.setCurrentItem(self.item)

    def _set_visible(self, visible):
        self._activate()
        self.layer.visible = visible

    def _set_opacity(self, percent):
        self._activate()
        self.helper.set_layer_opacity(self.layer, percent)

    def _set_gain(self, gain):
        self._activate()
        self.helper.set_layer_gain(self.layer, gain)

    def set_selected(self, selected):
        self.gain_row.setVisible(selected and self.helper.layer_has_gain(self.layer))
        self.adjustSize()
        self.item.setSizeHint(self.sizeHint())
        self.layer_list.scheduleDelayedItemsLayout()

    def _set_blending(self, additive):
        self._activate()
        self.visible.setChecked(True)
        self.helper.set_layer_blending(
            self.layer,
            self.helper.BLENDING_ADD if additive else self.helper.BLENDING_NORMAL,
        )
        self._update_blending_icon()

    def _update_blending_icon(self):
        self.additive.set_icon_name(
            icons.IconName.LAYERS_ADD if self.additive.isChecked() else icons.IconName.LAYERS
        )

    def _set_label_mode(self, mode):
        self._activate()
        self.visible.setChecked(True)
        current_mode, _color = self.helper.label_display_mode(self.layer)
        if mode == current_mode == self.helper.LABEL_CATEGORICAL:
            self.helper.reseed_label_colormap(self.layer)
        else:
            self.helper.set_label_display(self.layer, mode)
        self._refresh_previews()

    def _pick_color(self):
        self._activate()
        self.visible.setChecked(True)
        if self.is_labels:
            mode, color = self.helper.label_display_mode(self.layer)
            if mode == self.helper.LABEL_CATEGORICAL:
                self.helper.reseed_label_colormap(self.layer)
                self._refresh_previews()
                return
        else:
            color = self.helper.image_color(self.layer)
        qcolor = QtGui.QColor.fromRgbF(*map(float, color[:4]))
        self._color_dialog.setCurrentColor(qcolor)
        self._color_dialog.open(self._color_picked)

    def _color_picked(self):
        color = self._color_dialog.currentColor()
        rgba = (color.redF(), color.greenF(), color.blueF(), color.alphaF())
        if self.is_labels:
            mode, _old_color = self.helper.label_display_mode(self.layer)
            self.helper.set_label_display(self.layer, mode, rgba)
        else:
            self.helper.set_image_color(self.layer, rgba)
        self._refresh_previews()

    def _refresh_previews(self):
        if not self.is_labels:
            self.color_button.set_colors(
                [QtGui.QColor.fromRgbF(*self.helper.image_color(self.layer))]
            )
            self.color_button.setToolTip("Choose monochrome color")
            return

        mode, rgba = self.helper.label_display_mode(self.layer)
        color = QtGui.QColor("white") if rgba is None else QtGui.QColor.fromRgbF(*map(float, rgba))
        monochrome = [_with_brightness(color, level) for level in self.helper.MONOCHROME_LEVELS]
        previews = {
            self.helper.LABEL_CATEGORICAL: [
                QtGui.QColor.fromRgbF(*map(float, rgba))
                for rgba in self.helper.categorical_colors(self.layer)
            ],
            self.helper.LABEL_MASK: [color],
            self.helper.LABEL_MONOCHROME: monochrome,
        }
        self.color_button.set_colors(previews[mode])
        self.color_button.setToolTip(
            "Cycle categorical palette" if mode == self.helper.LABEL_CATEGORICAL else "Choose color"
        )
        self.color_button.set_mode_options(
            (
                (
                    self.helper.LABEL_CATEGORICAL,
                    "Categorical colors",
                    previews[self.helper.LABEL_CATEGORICAL],
                ),
                (
                    self.helper.LABEL_MASK,
                    "Single-color mask",
                    previews[self.helper.LABEL_MASK],
                ),
                (
                    self.helper.LABEL_MONOCHROME,
                    "Monochrome labels",
                    previews[self.helper.LABEL_MONOCHROME],
                ),
            )
        )


class _LayerHeaderWidget(QtWidgets.QWidget):
    def __init__(self, layer_list, item):
        super().__init__(layer_list)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        handle_space = QtWidgets.QLabel()
        handle_space.setFixedWidth(self.fontMetrics().horizontalAdvance("≡"))
        layout.addWidget(handle_space)
        visibility_space = QtWidgets.QWidget()
        visibility_space.setFixedWidth(QtWidgets.QCheckBox().sizeHint().width())
        layout.addWidget(visibility_space)
        for text, width, stretch in (
            ("Layer", None, 1),
            ("Color", layer_list.color_width, 0),
            ("Opacity", layer_list.opacity_width, 0),
            ("+", layer_list.blend_width, 0),
        ):
            label = QtWidgets.QLabel(text)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            if width is not None:
                label.setFixedWidth(width)
                label.setAlignment(QtCore.Qt.AlignCenter)
            layout.addWidget(label, stretch)
        item.setSizeHint(self.sizeHint())


class LayerListWidget(QtWidgets.QListWidget):
    """List of embedded Napari layers with direct presentation controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.helper = None
        self._initialize_column_widths()
        margins = [
            max(0, self.style().pixelMetric(metric, None, self))
            for metric in (
                QtWidgets.QStyle.PM_LayoutLeftMargin,
                QtWidgets.QStyle.PM_LayoutTopMargin,
                QtWidgets.QStyle.PM_LayoutRightMargin,
                QtWidgets.QStyle.PM_LayoutBottomMargin,
            )
        ]
        self.setViewportMargins(*margins)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.currentItemChanged.connect(self._selection_changed)
        self._move_shortcuts = []
        for sequence, offset in (("Alt+Up", -1), ("Alt+Down", 1)):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=offset: self.move_current_layer(step))
            self._move_shortcuts.append(shortcut)

    def _initialize_column_widths(self):
        color_text_width = self.fontMetrics().horizontalAdvance("Color") + 8
        menu_indicator = self.style().pixelMetric(QtWidgets.QStyle.PM_MenuButtonIndicator)
        self.color_width = max(color_text_width, self.fontMetrics().height() + 6 + menu_indicator)

        opacity = QtWidgets.QSpinBox(self)
        opacity.setRange(0, 100)
        opacity.setSuffix("%")
        self.opacity_width = max(
            opacity.sizeHint().width(), self.fontMetrics().horizontalAdvance("Opacity") + 8
        )
        opacity.deleteLater()

        additive = IconToolButton(self)
        self.blend_width = max(
            additive.sizeHint().width(), self.fontMetrics().horizontalAdvance("+") + 8
        )
        additive.deleteLater()

    def set_helper(self, helper):
        self.helper = helper
        self.rebuild()

    def rebuild(self, selected_layer=None):
        if selected_layer is None and self.currentItem() is not None:
            row = self.itemWidget(self.currentItem())
            selected_layer = None if row is None else getattr(row, "layer", None)
        self.clear()
        header_item = QtWidgets.QListWidgetItem()
        header_item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.addItem(header_item)
        self.setItemWidget(header_item, _LayerHeaderWidget(self, header_item))
        if self.helper is None:
            return
        selected_item = None
        # Napari model index 0 is the bottommost layer. Match Napari's own
        # layer list by showing the topmost layer first.
        for layer in reversed(self.helper.user_layers()):
            item = QtWidgets.QListWidgetItem()
            self.addItem(item)
            row = LayerRowWidget(self, item, layer)
            self.setItemWidget(item, row)
            item.setSizeHint(row.sizeHint())
            if layer is selected_layer:
                selected_item = item
        if selected_item is not None:
            self.setCurrentItem(selected_item)

    def _selection_changed(self, current, previous):
        if current is not None and self.row(current) == 0:
            self.setCurrentItem(previous)
            return
        for item, selected in ((previous, False), (current, True)):
            row = None if item is None else self.itemWidget(item)
            if isinstance(row, LayerRowWidget):
                row.set_selected(selected)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Space and not event.modifiers():
            item = self.currentItem()
            row = None if item is None else self.itemWidget(item)
            if row is not None:
                row.visible.toggle()
                event.accept()
                return
        super().keyPressEvent(event)

    def move_current_layer(self, offset):
        "Move the selected layer one row while retaining its selection."
        item = self.currentItem()
        if item is None:
            return
        source_index = self.row(item) - 1
        target_index = source_index + offset
        if not 0 <= target_index < self.count() - 1:
            return
        row = self.itemWidget(item)
        self._move_layer_to_display_index(row.layer, target_index)
        self.rebuild(row.layer)

    def _move_layer_to_display_index(self, layer, display_index):
        model_index = len(self.helper.viewer.layers) - 1 - display_index
        self.helper.move_layer(layer, model_index)

    def dropEvent(self, event):
        source_item = self.currentItem()
        source_row = None if source_item is None else self.itemWidget(source_item)
        if source_row is None:
            event.ignore()
            return

        target_item = self.itemAt(event.pos())
        if target_item is source_item:
            event.acceptProposedAction()
            return
        if target_item is None:
            target_index = self.count() - 2
        elif self.row(target_item) == 0:
            target_index = 0
        else:
            remaining = [
                self.itemWidget(self.item(index)).layer
                for index in range(1, self.count())
                if self.item(index) is not source_item
            ]
            target_layer = self.itemWidget(target_item).layer
            insert_after = event.pos().y() >= self.visualItemRect(target_item).center().y()
            target_index = remaining.index(target_layer) + int(insert_after)

        self._move_layer_to_display_index(source_row.layer, target_index)
        event.acceptProposedAction()
        selected_layer = source_row.layer
        QtCore.QTimer.singleShot(0, lambda: self.rebuild(selected_layer))

    def reload_appearance(self):
        for index in range(1, self.count()):
            row = self.itemWidget(self.item(index))
            if row is not None:
                row.update()
                row._refresh_previews()
                row.additive.reload_icon()
