"""Rendering preferences and explicit consent after viewer initialization failures."""

import json
import os

import pytest
from qtpy import QtCore, QtWidgets

from exhale import rendering
from exhale.settings_dialog import SettingsDialog


@pytest.fixture
def settings(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    yield settings
    app.processEvents()


@pytest.mark.parametrize(
    ("choice", "accepted", "continue_session", "saved"),
    [
        ("quit_option", True, False, False),
        ("continue_option", True, True, False),
        ("software_option", True, False, True),
        ("software_option", False, False, False),
    ],
)
def test_failure_choice_persists_only_accepted_software_preference(
    settings, monkeypatch, choice, accepted, continue_session, saved
):
    monkeypatch.setattr(rendering.sys, "platform", "win32")
    monkeypatch.delenv("QT_OPENGL", raising=False)
    dialog = rendering.RenderingFailureDialog(settings, "original traceback")
    assert dialog.quit_option.isChecked()
    assert dialog.action_button.text() == "Quit"
    getattr(dialog, choice).setChecked(True)
    expected = {
        "quit_option": "Quit",
        "continue_option": "Continue",
        "software_option": "Restart",
    }
    assert dialog.action_button.text() == expected[choice]
    QtCore.QTimer.singleShot(0, dialog.accept if accepted else dialog.reject)
    if saved:
        with pytest.raises(rendering.RenderingRestartRequested):
            dialog.allow_degraded_session()
    else:
        assert dialog.allow_degraded_session() == continue_session
    assert settings.value(rendering.SOFTWARE_OPENGL_KEY, False, type=bool) == saved
    assert dialog.error_details == "original traceback"
    dialog.deleteLater()


def test_failed_software_rendering_cannot_be_selected_again(settings, monkeypatch):
    monkeypatch.setenv("QT_OPENGL", "software")
    dialog = rendering.RenderingFailureDialog(settings, "software failed")
    assert not dialog.software_option.isEnabled()
    dialog.deleteLater()


def test_error_details_open_full_traceback_in_separate_dialog(settings, monkeypatch):
    dialog = rendering.RenderingFailureDialog(settings, "original full traceback")
    reported = []
    monkeypatch.setattr(
        rendering.ExceptionDetailsDialog, "show_exception", lambda self, **kw: reported.append(kw)
    )
    dialog.details_button.click()
    assert isinstance(dialog._details_dialog, rendering.ExceptionDetailsDialog)
    assert reported[0]["details"] == "original full traceback"
    assert dialog.details_button.text() == "Show error details"
    assert not dialog.details_button.isCheckable()
    assert not dialog.findChildren(
        QtWidgets.QPlainTextEdit, options=QtCore.Qt.FindDirectChildrenOnly
    )
    dialog.deleteLater()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_configure_rendering_applies_saved_preference_before_qt_creation(
    settings, monkeypatch, platform
):
    monkeypatch.setattr(rendering.sys, "platform", platform)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.delenv("LIBGL_ALWAYS_SOFTWARE", raising=False)
    attributes = []
    monkeypatch.setattr(QtCore.QCoreApplication, "setAttribute", attributes.append)
    settings.setValue(rendering.SOFTWARE_OPENGL_KEY, True)
    rendering.configure_rendering(settings)
    assert os.environ["QT_OPENGL"] == "software"
    assert attributes == [QtCore.Qt.AA_UseSoftwareOpenGL]
    assert os.environ.get("LIBGL_ALWAYS_SOFTWARE") == ("1" if platform == "linux" else None)


def test_default_renderer_preserves_environment(settings, monkeypatch):
    monkeypatch.setenv("QT_OPENGL", "desktop")
    monkeypatch.setattr(
        QtCore.QCoreApplication,
        "setAttribute",
        lambda *_: pytest.fail("Default rendering must not change Qt attributes"),
    )
    rendering.configure_rendering(settings)
    assert os.environ["QT_OPENGL"] == "desktop"


def test_software_preference_can_be_changed_in_settings(settings, monkeypatch):
    monkeypatch.setattr(rendering.sys, "platform", "linux")
    dialog = SettingsDialog(settings)
    dialog.softwareOpenGLCheckBox.setChecked(True)
    dialog.accept()
    reopened = SettingsDialog(settings)
    assert reopened.softwareOpenGLCheckBox.isChecked()
    reopened.softwareOpenGLCheckBox.setChecked(False)
    reopened.accept()
    assert not settings.value(rendering.SOFTWARE_OPENGL_KEY, True, type=bool)
    dialog.deleteLater()
    reopened.deleteLater()


def test_main_window_requires_consent_before_disabling_tabs(settings, monkeypatch):
    from exhale import main_window

    monkeypatch.setattr(QtCore, "QSettings", lambda *_args, **_kwargs: settings)

    def fail_view(_self):
        raise RuntimeError("test viewer initialization failed")

    monkeypatch.setattr(main_window.AnalysisController, "initialize_view", fail_view)
    received = []

    def continue_session(dialog):
        received.append(dialog.error_details)
        return True

    monkeypatch.setattr(
        rendering.RenderingFailureDialog, "allow_degraded_session", continue_session
    )
    window = main_window.MainWindow()
    assert "test viewer initialization failed" in received[0]
    for tab in (window.analysisTab, window.clusteringTab):
        assert not window.tabWidget.isTabEnabled(window.tabWidget.indexOf(tab))
    warning = next(
        button
        for button in window.statusBar().findChildren(QtWidgets.QPushButton)
        if "unavailable" in button.text()
    )
    reported = []
    monkeypatch.setattr(
        window._exception_dialog, "show_exception", lambda **kw: reported.append(kw)
    )
    warning.click()
    assert reported[0]["details"] == received[0]
    window.update_controller.shutdown()
    window.clustering_controller.shutdown()
    window.project_state_manager._autosave_timer.stop()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_main_window_quits_when_degraded_operation_is_declined(settings, monkeypatch):
    from exhale import main_window

    monkeypatch.setattr(QtCore, "QSettings", lambda *_args, **_kwargs: settings)

    def fail_view(_self):
        raise RuntimeError("test viewer initialization failed")

    monkeypatch.setattr(main_window.AnalysisController, "initialize_view", fail_view)
    monkeypatch.setattr(
        rendering.RenderingFailureDialog, "allow_degraded_session", lambda _self: False
    )
    window = main_window.MainWindow.__new__(main_window.MainWindow)
    with pytest.raises(SystemExit) as error:
        main_window.MainWindow.__init__(window)
    assert error.value.code == 0
    window.update_controller.shutdown()
    window.clustering_controller.shutdown()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_older_native_launcher_requires_manual_restart(settings, monkeypatch):
    monkeypatch.setenv("EXHALE_NATIVE_INSTALLATION", json.dumps({"protocol": "1"}))
    monkeypatch.delenv("QT_OPENGL", raising=False)
    dialog = rendering.RenderingFailureDialog(settings, "traceback")
    dialog.software_option.setChecked(True)
    assert dialog.action_button.text() == "Save and quit"
    QtCore.QTimer.singleShot(0, dialog.accept)
    assert not dialog.allow_degraded_session()
    assert settings.value(rendering.SOFTWARE_OPENGL_KEY, False, type=bool)
    dialog.deleteLater()


def test_native_restart_hands_request_to_launcher_without_spawning(monkeypatch, tmp_path):
    from exhale import updates

    request = tmp_path / "update-request.json"
    monkeypatch.setenv("EXHALE_NATIVE_INSTALLATION", json.dumps({"restart": "1"}))
    monkeypatch.setattr(
        updates,
        "native_installation",
        lambda: {"request": str(request), "token": "current-token", "environment": "env-working"},
    )
    rendering.restart_application()
    assert json.loads(request.read_text()) == {
        "action": "restart",
        "token": "current-token",
        "environment": "env-working",
    }
    assert not request.with_suffix(".tmp").exists()


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_direct_restart_preserves_interpreter_and_arguments(monkeypatch, platform, tmp_path):
    monkeypatch.delenv("EXHALE_NATIVE_INSTALLATION", raising=False)
    monkeypatch.setattr(rendering.sys, "platform", platform)
    script = tmp_path / "run_exhale.py"
    monkeypatch.setattr(rendering.sys, "argv", [str(script), "--project", "my project"])
    calls = []
    monkeypatch.setattr(rendering.os, "execv", lambda exe, args: calls.append(args))
    monkeypatch.setattr(rendering.subprocess, "Popen", lambda args: calls.append(args))
    rendering.restart_application()
    assert calls == [[rendering.sys.executable, str(script), "--project", "my project"]]


@pytest.mark.parametrize(
    ("qt_platform", "integration", "expected"),
    [
        ("wayland", "", "egl"),
        ("wayland-egl", "", "egl"),
        ("xcb", "", "glx"),
        ("xcb", "xcb_egl", "egl"),
        ("offscreen", "", None),
    ],
)
def test_pyopengl_matches_live_qt_backend(monkeypatch, qt_platform, integration, expected):
    from types import SimpleNamespace

    monkeypatch.setattr(rendering.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("QT_XCB_GL_INTEGRATION", integration)
    monkeypatch.delenv("PYOPENGL_PLATFORM", raising=False)
    app = SimpleNamespace(platformName=lambda: qt_platform)
    rendering.configure_pyopengl_platform(app)
    assert os.environ.get("PYOPENGL_PLATFORM") == expected
    monkeypatch.setenv("PYOPENGL_PLATFORM", "custom")
    rendering.configure_pyopengl_platform(app)
    assert os.environ["PYOPENGL_PLATFORM"] == "custom"
