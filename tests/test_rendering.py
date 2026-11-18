"""Rendering preferences and explicit consent after viewer initialization failures."""

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
        "software_option": "Save and quit",
    }
    assert dialog.action_button.text() == expected[choice]
    QtCore.QTimer.singleShot(0, dialog.accept if accepted else dialog.reject)
    assert dialog.allow_degraded_session() == continue_session
    assert settings.value(rendering.SOFTWARE_OPENGL_KEY, False, type=bool) == saved
    assert dialog.details.toPlainText() == "original traceback"
    dialog.deleteLater()


def test_failed_software_rendering_cannot_be_selected_again(settings, monkeypatch):
    monkeypatch.setenv("QT_OPENGL", "software")
    dialog = rendering.RenderingFailureDialog(settings, "software failed")
    assert not dialog.software_option.isEnabled()
    dialog.details_button.click()
    assert not dialog.details.isHidden()
    assert dialog.details_button.text() == "Hide error details"
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
        received.append(dialog.details.toPlainText())
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
