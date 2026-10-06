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
        self.setIcon(
            icons.icon(self.icon_name)
            if self.icon_name is not None else QtGui.QIcon())

    def sizeHint(self):
        option = QtWidgets.QStyleOptionButton()
        option.initFrom(self)
        content = self.fontMetrics().size(QtCore.Qt.TextShowMnemonic, "M")
        size = self.style().sizeFromContents(
            QtWidgets.QStyle.CT_PushButton, option, content, self)
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
        if (watched is self.visible_widget
                and event.type() == QtCore.QEvent.Show
                and not self.initialized):
            QtCore.QTimer.singleShot(0, self.initialize)
        return super().eventFilter(watched, event)

    def initialize(self):
        if (self.saved_state is not None
                and self.splitter.restoreState(self.saved_state)):
            self.initialized = True
            return

        count = self.splitter.count()
        if len(self.proportions) != count or any(p <= 0 for p in self.proportions):
            raise ValueError("Splitter proportions must be positive and match its panes")
        extent = (self.splitter.width()
                  if self.splitter.orientation() == QtCore.Qt.Horizontal
                  else self.splitter.height())
        available = extent - self.splitter.handleWidth() * (count - 1)
        if available <= 0:
            return

        total = sum(self.proportions)
        sizes = [round(available * proportion / total)
                 for proportion in self.proportions[:-1]]
        sizes.append(available - sum(sizes))
        self.splitter.setSizes(sizes)
        self.initialized = True


def initialize_splitter_on_show(splitter, visible_widget, proportions,
                                saved_state=None):
    """Apply saved state or default proportions after layout is available."""
    return _SplitterInitializer(
        splitter, visible_widget, proportions, saved_state)
