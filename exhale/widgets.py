"""Small reusable Qt widget helpers."""

from qtpy import QtCore, QtGui, QtWidgets

from . import icons


class IconToolButton(QtWidgets.QToolButton):
    """A square icon-only action button aligned with push buttons."""

    def __init__(self, icon_name=None, parent=None):
        if isinstance(icon_name, QtWidgets.QWidget):
            parent = icon_name
            icon_name = None
        super().__init__(parent)
        self.icon_name = icon_name
        self._update_icon_size()
        self.reload_icon()

    def set_icon_name(self, icon_name):
        self.icon_name = icon_name
        self.reload_icon()

    def reload_icon(self):
        self.setIcon(icons.icon(self.icon_name) if self.icon_name is not None else QtGui.QIcon())

    def sizeHint(self):
        option = QtWidgets.QStyleOptionButton()
        option.initFrom(self)
        content = self.fontMetrics().size(QtCore.Qt.TextShowMnemonic, "M")
        size = self.style().sizeFromContents(QtWidgets.QStyle.CT_PushButton, option, content, self)
        return QtCore.QSize(size.height(), size.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def changeEvent(self, event):
        if event.type() in (QtCore.QEvent.FontChange, QtCore.QEvent.StyleChange):
            self._update_icon_size()
        super().changeEvent(event)

    def _update_icon_size(self):
        extent = self.fontMetrics().height()
        self.setIconSize(QtCore.QSize(extent, extent))


class _IconCheckStyle(QtWidgets.QProxyStyle):
    """Give item-view check indicators enough room for the 24-unit SVGs."""

    INDICATOR_SIZE = 24

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QtWidgets.QStyle.PixelMetric.PM_IndicatorWidth,
            QtWidgets.QStyle.PixelMetric.PM_IndicatorHeight,
        ):
            return self.INDICATOR_SIZE
        return super().pixelMetric(metric, option, widget)


class IconCheckDelegate(QtWidgets.QStyledItemDelegate):
    """Paint Exhale icons in the standard item-view check-indicator rectangle."""

    DEFAULT_ICONS = {
        QtCore.Qt.CheckState.Unchecked: icons.IconName.CHECKBOX,
        QtCore.Qt.CheckState.PartiallyChecked: icons.IconName.CHECKBOX_DEFAULT_MARKED,
        QtCore.Qt.CheckState.Checked: icons.IconName.CHECKBOX_MARKED,
    }

    def __init__(self, parent=None, icon_name_for_state=None):
        super().__init__(parent)
        self._icon_name_for_state = icon_name_for_state
        if isinstance(parent, QtWidgets.QAbstractItemView) and not isinstance(
            parent.style(), _IconCheckStyle
        ):
            indicator_style = _IconCheckStyle()
            indicator_style.setParent(parent)
            parent.setStyle(indicator_style)

    def indicator_icon_name(self, index, state):
        """Return the semantic icon name for one model check state."""
        if self._icon_name_for_state is not None:
            return self._icon_name_for_state(index, state)
        return self.DEFAULT_ICONS[state]

    @staticmethod
    def indicator_rect(option, index):
        """Return the active style's standard check-indicator rectangle."""
        widget = option.widget
        style = widget.style() if widget is not None else QtWidgets.QApplication.style()
        return style.subElementRect(
            QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option,
            widget,
        )

    def paint(self, painter, option, index):
        styled = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        if not (styled.features & QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator):
            super().paint(painter, option, index)
            return

        indicator_rect = self.indicator_rect(styled, index)
        widget = styled.widget
        style = widget.style() if widget is not None else QtWidgets.QApplication.style()

        style.drawPrimitive(
            QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem,
            styled,
            painter,
            widget,
        )
        content = QtWidgets.QStyleOptionViewItem(styled)
        content.features &= ~QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        if content.direction == QtCore.Qt.LayoutDirection.RightToLeft:
            content.rect.setRight(indicator_rect.left())
        else:
            content.rect.setLeft(indicator_rect.right())
        style.drawControl(
            QtWidgets.QStyle.ControlElement.CE_ItemViewItem,
            content,
            painter,
            widget,
        )

        mode = (
            QtGui.QIcon.Mode.Normal
            if styled.state & QtWidgets.QStyle.StateFlag.State_Enabled
            else QtGui.QIcon.Mode.Disabled
        )
        icons.icon(self.indicator_icon_name(index, styled.checkState)).paint(
            painter,
            indicator_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            mode,
            QtGui.QIcon.State.Off,
        )


class _SplitterInitializer(QtCore.QObject):
    """Restore or proportion a splitter once its containing widget is shown."""

    def __init__(self, splitter, visible_widget, proportions, saved_state=None):
        super().__init__(splitter)
        self.splitter = splitter
        self.visible_widget = visible_widget
        self.proportions = tuple(proportions)
        self.saved_state = saved_state
        self.initialized = False
        visible_widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            watched is self.visible_widget
            and event.type() == QtCore.QEvent.Show
            and not self.initialized
        ):
            QtCore.QTimer.singleShot(0, self.initialize)
        return super().eventFilter(watched, event)

    def initialize(self):
        if self.saved_state is not None and self.splitter.restoreState(self.saved_state):
            if all(size > 0 for size in self.splitter.sizes()):
                self.initialized = True
                return

        count = self.splitter.count()
        if len(self.proportions) != count or any(p <= 0 for p in self.proportions):
            raise ValueError("Splitter proportions must be positive and match its panes")
        extent = (
            self.splitter.width()
            if self.splitter.orientation() == QtCore.Qt.Horizontal
            else self.splitter.height()
        )
        available = extent - self.splitter.handleWidth() * (count - 1)
        if available <= 0:
            return

        total = sum(self.proportions)
        sizes = [round(available * proportion / total) for proportion in self.proportions[:-1]]
        sizes.append(available - sum(sizes))
        self.splitter.setSizes(sizes)
        self.initialized = True


def initialize_splitter_on_show(splitter, visible_widget, proportions, saved_state=None):
    """Apply saved state or default proportions after layout is available."""
    return _SplitterInitializer(splitter, visible_widget, proportions, saved_state)
