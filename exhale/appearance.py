"""Application colour-scheme selection and palette handling."""

from __future__ import annotations

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtWidgets import QApplication

COLOR_SCHEME_KEY = "appearance/color_scheme"
COLOR_SCHEMES = ("system", "light", "dark")
_manager = None


class SplitterGripStyle(QtWidgets.QProxyStyle):
    """A restrained, palette-aware splitter grip for Fusion only."""

    def __init__(self):
        super().__init__("Fusion")
        self.setObjectName("fusion")

    def drawControl(self, element, option, painter, widget=None):
        if element != QtWidgets.QStyle.CE_Splitter or not isinstance(widget, QtWidgets.QSplitter):
            return super().drawControl(element, option, painter, widget)

        # Leave the handle background and hit area unchanged. In particular,
        # do not also override dock-widget separators drawn with CE_Splitter.
        rect = QtCore.QRectF(option.rect)
        vertical = widget.orientation() == QtCore.Qt.Horizontal
        length = min(24.0, (rect.height() if vertical else rect.width()) - 4.0)
        thickness = min(2.0, rect.width() if vertical else rect.height())
        if length <= 0 or thickness <= 0:
            return
        center = rect.center()
        grip = (
            QtCore.QRectF(center.x() - thickness / 2, center.y() - length / 2, thickness, length)
            if vertical
            else QtCore.QRectF(
                center.x() - length / 2, center.y() - thickness / 2, length, thickness
            )
        )
        color = option.palette.color(QtGui.QPalette.WindowText)
        active = option.state & (QtWidgets.QStyle.State_MouseOver | QtWidgets.QStyle.State_Sunken)
        color.setAlphaF(0.5 if active else 0.3)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(grip, thickness / 2, thickness / 2)
        painter.restore()


def _install_splitter_style(app) -> None:
    # An explicit allowlist: leave untested and native platform styles alone.
    if app.style().objectName().casefold() == "fusion" and not isinstance(
        app.style(), SplitterGripStyle
    ):
        palette = app.palette()
        app.setStyle(SplitterGripStyle())
        app.setPalette(palette)


class AppearanceManager(QtCore.QObject):
    """Apply the selected palette and report subsequent palette changes."""

    changed = QtCore.Signal()

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._scheme = "system"
        self._applying = False
        QApplication.instance().paletteChanged.connect(self._application_palette_changed)
        self.apply_configured_scheme()

    def apply_configured_scheme(self) -> None:
        self.set_scheme(self.settings.value(COLOR_SCHEME_KEY, "system"))

    def set_scheme(self, scheme: str) -> None:
        if scheme not in COLOR_SCHEMES:
            raise ValueError(f"Unknown colour scheme: {scheme}")
        if scheme == self._scheme and getattr(self, "_initialized", False):
            return

        self._scheme = scheme
        self._applying = True
        try:
            app = QApplication.instance()
            if scheme == "system" and getattr(self, "_initialized", False):
                app.setPalette(app.style().standardPalette())
            elif scheme == "light":
                app.setPalette(_light_palette())
            elif scheme == "dark":
                app.setPalette(_dark_palette())
        finally:
            self._applying = False
        self._initialized = True
        self.changed.emit()

    def _application_palette_changed(self, _palette) -> None:
        if self._scheme == "system" and not self._applying:
            self.changed.emit()


def initialize(
    settings: QtCore.QSettings,
) -> AppearanceManager:
    """Create the application-wide appearance manager."""
    global _manager
    if _manager is None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("Create QApplication before appearance manager")
        _install_splitter_style(app)
        _manager = AppearanceManager(settings, app)
    return _manager


def manager() -> AppearanceManager:
    if _manager is None:
        raise RuntimeError("Appearance has not been initialized")
    return _manager


def is_dark() -> bool:
    app = QApplication.instance()
    return app.palette().color(QtGui.QPalette.Window).lightness() < 128


def _light_palette() -> QtGui.QPalette:
    style = QtWidgets.QStyleFactory.create("Fusion")
    return style.standardPalette()


def _dark_palette() -> QtGui.QPalette:
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#303030"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#202020"))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#2c2c2c"))
    palette.setColor(QtGui.QPalette.Light, QtGui.QColor("#606060"))
    palette.setColor(QtGui.QPalette.Midlight, QtGui.QColor("#484848"))
    palette.setColor(QtGui.QPalette.Mid, QtGui.QColor("#292929"))
    palette.setColor(QtGui.QPalette.Dark, QtGui.QColor("#101010"))
    palette.setColor(QtGui.QPalette.Shadow, QtGui.QColor("#080808"))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#202020"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#383838"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#bfa3f9"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#60469a"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    disabled = QtGui.QColor("#808080")
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        palette.setColor(QtGui.QPalette.Disabled, role, disabled)
    return palette
