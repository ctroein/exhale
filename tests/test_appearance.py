"""Theme switches must keep readable palettes and restore the platform theme."""

import sys

import pytest
from qtpy import QtCore, QtGui, QtWidgets

from exhale import appearance
from exhale.widgets import IconCheckDelegate


@pytest.fixture
def manager(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    original_palette = app.palette()
    original_style = app.style().objectName()
    appearance._install_application_style(app)
    hints = app.styleHints()
    if hasattr(hints, "unsetColorScheme"):
        hints.unsetColorScheme()
    settings = QtCore.QSettings(str(tmp_path / "appearance.ini"), QtCore.QSettings.IniFormat)
    manager = appearance.AppearanceManager(settings)
    yield manager
    manager.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    if hasattr(hints, "unsetColorScheme"):
        hints.unsetColorScheme()
    if app.style().objectName() != original_style:
        app.setStyle(original_style)
    app.setPalette(original_palette)


def test_light_palette_is_light_even_when_platform_prefers_dark(manager):
    hints = QtWidgets.QApplication.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(QtCore.Qt.ColorScheme.Dark)
    palette = appearance._light_palette()
    for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
        for background, foreground in (
            (QtGui.QPalette.Window, QtGui.QPalette.WindowText),
            (QtGui.QPalette.Base, QtGui.QPalette.Text),
            (QtGui.QPalette.Button, QtGui.QPalette.ButtonText),
        ):
            assert palette.color(group, background).lightness() > 200
            assert palette.color(group, foreground).lightness() < 128


def test_switching_schemes_restores_current_system_palette(manager):
    app = QtWidgets.QApplication.instance()
    roles = (
        QtGui.QPalette.Window,
        QtGui.QPalette.WindowText,
        QtGui.QPalette.Base,
        QtGui.QPalette.Text,
        QtGui.QPalette.Button,
        QtGui.QPalette.ButtonText,
    )
    system_colors = [app.palette().color(role) for role in roles]
    for scheme in ("light", "dark", "light", "system"):
        manager.set_scheme(scheme)
        app.processEvents()
        if scheme != "system":
            assert appearance.is_dark() == (scheme == "dark")
    assert [app.palette().color(role) for role in roles] == system_colors


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native theme drawing")
def test_windows_native_scheme_tracks_explicit_palette(manager):
    app = QtWidgets.QApplication.instance()
    if not hasattr(app.styleHints(), "setColorScheme"):
        pytest.skip("Native scheme override requires Qt 6.8")
    for scheme, expected in (
        ("light", QtCore.Qt.ColorScheme.Light),
        ("dark", QtCore.Qt.ColorScheme.Dark),
    ):
        manager.set_scheme(scheme)
        assert app.styleHints().colorScheme() == expected
        assert app.style().objectName() == ("windowsvista" if scheme == "light" else "windows11")


@pytest.mark.skipif(sys.platform != "win32", reason="Qt 6.7 Windows fallback")
def test_windows_without_native_override_uses_fusion_for_explicit_schemes(manager, monkeypatch):
    app = QtWidgets.QApplication.instance()
    style = app.style().objectName()
    view = QtWidgets.QListWidget()
    view.setItemDelegate(IconCheckDelegate(view))
    try:
        monkeypatch.setattr(QtWidgets.QApplication, "styleHints", staticmethod(object))
        manager.set_scheme("light")
        app.processEvents()
        assert app.style().objectName().casefold() == "fusion"
        assert view.style().baseStyle().objectName().casefold() == "fusion"
        assert not appearance.is_dark()
        manager.set_scheme("dark")
        assert appearance.is_dark()
        manager.set_scheme("system")
        app.processEvents()
        assert app.style().objectName() == style
        assert view.style().baseStyle().objectName() == style
    finally:
        view.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native style color caches")
def test_item_view_frames_follow_light_dark_switches(manager):
    app = QtWidgets.QApplication.instance()
    if app.platformName() != "windows":
        pytest.skip("Requires the Windows platform plugin")
    view = QtWidgets.QListWidget()
    view.setItemDelegate(IconCheckDelegate(view))

    def frame_image(style):
        image = QtGui.QImage(100, 50, QtGui.QImage.Format_ARGB32)
        image.fill(app.palette().color(QtGui.QPalette.Window))
        option = QtWidgets.QStyleOptionFrame()
        option.initFrom(view)
        option.rect = QtCore.QRect(0, 0, 100, 50)
        option.palette = app.palette()
        option.lineWidth = 1
        painter = QtGui.QPainter(image)
        style.drawPrimitive(QtWidgets.QStyle.PE_FrameGroupBox, option, painter, view)
        painter.end()
        return image

    try:
        frames = {}
        for scheme in ("light", "dark", "light"):
            manager.set_scheme(scheme)
            app.processEvents()
            fresh_style = QtWidgets.QStyleFactory.create(
                "windowsvista" if scheme == "light" else app.style().objectName()
            )
            assert frame_image(view.style()) == frame_image(fresh_style)
            assert frame_image(app.style()) == frame_image(fresh_style)
            frames[scheme] = frame_image(view.style())
        assert frames["light"] != frames["dark"]
    finally:
        view.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.mark.parametrize("style_name", ["Fusion", "windowsvista", "windows11"])
@pytest.mark.parametrize("orientation", [QtCore.Qt.Horizontal, QtCore.Qt.Vertical])
def test_splitter_draws_grip_over_inherited_background(manager, style_name, orientation):
    manager.set_scheme("light")
    app = QtWidgets.QApplication.instance()
    if style_name.casefold() not in [name.casefold() for name in QtWidgets.QStyleFactory.keys()]:
        pytest.skip("Style unavailable on this platform")
    app.setStyle(style_name)
    appearance._install_application_style(app)

    class PaintedParent(QtWidgets.QWidget):
        color = QtGui.QColor("#83b49d")

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            painter.fillRect(self.rect(), self.color)

    host = PaintedParent()
    splitter = QtWidgets.QSplitter(orientation)
    splitter.setHandleWidth(8)
    for _ in range(2):
        splitter.addWidget(QtWidgets.QWidget())
    QtWidgets.QVBoxLayout(host).addWidget(splitter)
    host.resize(240, 240)
    host.show()
    try:
        for color in ("#83b49d", "#36283e"):
            host.color = QtGui.QColor(color)
            host.update()
            app.processEvents()
            handle = splitter.handle(1)
            image = host.grab().toImage()
            corner = handle.mapTo(host, QtCore.QPoint(0, 0))
            assert image.pixelColor(corner) == host.color
            center = handle.mapTo(host, handle.rect().center())
            assert image.pixelColor(center) != host.color
    finally:
        host.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
