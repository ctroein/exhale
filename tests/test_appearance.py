"""Theme switches must keep readable palettes and restore the platform theme."""

import sys

import pytest
from qtpy import QtCore, QtGui, QtWidgets

from exhale import appearance


@pytest.fixture
def manager(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    original_palette = app.palette()
    original_style = app.style().objectName()
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
    style = app.style().objectName()
    for scheme, expected in (
        ("light", QtCore.Qt.ColorScheme.Light),
        ("dark", QtCore.Qt.ColorScheme.Dark),
    ):
        app.styleHints().setColorScheme(expected)
        app.setPalette(QtGui.QPalette())
        native_palette = app.palette()
        manager.set_scheme(scheme)
        assert app.styleHints().colorScheme() == expected
        assert app.style().objectName() == style
        assert app.palette() == native_palette


@pytest.mark.skipif(sys.platform != "win32", reason="Qt 6.7 Windows fallback")
def test_windows_without_native_override_uses_fusion_for_explicit_schemes(manager, monkeypatch):
    app = QtWidgets.QApplication.instance()
    style = app.style().objectName()
    monkeypatch.setattr(QtWidgets.QApplication, "styleHints", staticmethod(object))
    manager.set_scheme("light")
    assert app.style().objectName().casefold() == "fusion"
    assert not appearance.is_dark()
    manager.set_scheme("dark")
    assert appearance.is_dark()
    manager.set_scheme("system")
    assert app.style().objectName() == style
