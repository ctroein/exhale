"""Application colour-scheme selection and palette handling."""

from __future__ import annotations

import sys

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtWidgets import QApplication

COLOR_SCHEME_KEY = "appearance/color_scheme"
FONT_SCALE_KEY = "appearance/font_scale"
COLOR_SCHEMES = ("system", "light", "dark")
_manager = None


class SplitterStyle(QtWidgets.QProxyStyle):
    """Inherit splitter backgrounds and draw a shared palette-aware grip."""

    def __init__(self, style_name):
        super().__init__(style_name)
        self.setObjectName(style_name.casefold())

    def drawControl(self, element, option, painter, widget=None):
        if element != QtWidgets.QStyle.CE_Splitter or not isinstance(
            widget, (QtWidgets.QSplitter, QtWidgets.QSplitterHandle)
        ):
            return super().drawControl(element, option, painter, widget)
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


def _install_application_style(app) -> None:
    if not isinstance(app.style(), SplitterStyle):
        palette = app.palette()
        app.setStyle(SplitterStyle(app.style().objectName()))
        app.setPalette(palette)


class AppearanceManager(QtCore.QObject):
    """Apply the selected palette and report subsequent palette changes."""

    changed = QtCore.Signal()

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._scheme = "system"
        self._applying = False
        self._system_style = QApplication.instance().style().objectName()
        QApplication.instance().paletteChanged.connect(self._application_palette_changed)
        self._base_font = QApplication.font()
        self.font_scale = 100
        self.apply_configured_scheme()
        try:
            scale = int(settings.value(FONT_SCALE_KEY, 100))
        except (TypeError, ValueError):
            scale = 100
        self.set_font_scale(scale)

    @property
    def scheme(self) -> str:
        return self._scheme

    def set_font_scale(self, percent: int) -> None:
        percent = min(200, max(50, round(percent / 10) * 10))
        if percent == self.font_scale:
            return
        self.font_scale = percent
        font = QtGui.QFont(self._base_font)
        if font.pixelSize() > 0:
            font.setPixelSize(max(1, round(font.pixelSize() * percent / 100)))
        else:
            font.setPointSizeF(font.pointSizeF() * percent / 100)
        QApplication.setFont(font)
        self.settings.setValue(FONT_SCALE_KEY, percent)

    def select_scheme(self, scheme: str) -> None:
        self.set_scheme(scheme)
        self.settings.setValue(COLOR_SCHEME_KEY, scheme)

    def apply_configured_scheme(self) -> None:
        self.set_scheme(self.settings.value(COLOR_SCHEME_KEY, "system"))

    def set_scheme(self, scheme: str, *, force: bool = False) -> None:
        if scheme not in COLOR_SCHEMES:
            raise ValueError(f"Unknown colour scheme: {scheme}")
        if not force and scheme == self._scheme and getattr(self, "_initialized", False):
            return

        self._scheme = scheme
        self._applying = True
        try:
            app = QApplication.instance()
            native_palette = False
            if sys.platform == "win32":
                set_color_scheme = getattr(app.styleHints(), "setColorScheme", None)
                if set_color_scheme is not None:
                    # Native Windows controls also consult the platform theme.
                    # A palette override alone leaves their drawing out of sync.
                    set_color_scheme(
                        {
                            "system": QtCore.Qt.ColorScheme.Unknown,
                            "light": QtCore.Qt.ColorScheme.Light,
                            "dark": QtCore.Qt.ColorScheme.Dark,
                        }[scheme]
                    )
                    native_palette = True
                    style = self._system_style
                    if (
                        style.casefold() == "windows11"
                        and app.styleHints().colorScheme() == QtCore.Qt.ColorScheme.Light
                    ):
                        # The Win32/UXTheme style supplies the complete normal
                        # Windows light palette, backgrounds, frames and metrics.
                        style = "windowsvista"
                else:
                    # Qt 6.7 cannot override the native color scheme. Fusion
                    # honors our explicit palettes; System restores the style.
                    style = self._system_style if scheme == "system" else "fusion"
                if app.style().objectName().casefold() != style.casefold():
                    app.setStyle(style)
                _install_application_style(app)
            if scheme == "system" or native_palette:
                # An unresolved palette removes application overrides and lets
                # Qt supply the current platform palette, including OS changes.
                app.setPalette(QtGui.QPalette())
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
            self.set_scheme("system", force=True)


def initialize(
    settings: QtCore.QSettings,
) -> AppearanceManager:
    """Create the application-wide appearance manager."""
    global _manager
    if _manager is None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("Create QApplication before appearance manager")
        _install_application_style(app)
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
    # Fusion's standardPalette follows the OS scheme on recent Qt versions.
    # Derive a light palette from an explicit light button/background color.
    palette = QtGui.QPalette(QtGui.QColor("#efefef"))
    palette.setColor(QtGui.QPalette.Accent, palette.color(QtGui.QPalette.Highlight))
    return palette


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
    palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor("#909090"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#383838"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f0f0f0"))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#bfa3f9"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#60469a"))
    palette.setColor(QtGui.QPalette.Accent, QtGui.QColor("#60469a"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    disabled = QtGui.QColor("#808080")
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        palette.setColor(QtGui.QPalette.Disabled, role, disabled)
    return palette
