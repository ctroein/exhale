"""Application update scheduling and preference persistence without network access."""

import pytest
from qtpy import QtCore, QtWidgets

from exhale import appearance, updates
from exhale.settings_dialog import SettingsDialog
from exhale.update_controller import UpdateController


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    window.settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    window.update_controller = UpdateController(window)
    appearance.initialize(window.settings)
    yield window
    window.update_controller.shutdown()
    window.close()
    app.processEvents()


def test_daily_checks_respect_disabled_setting_and_last_attempt(window, monkeypatch):
    controller = window.update_controller
    calls = []
    monkeypatch.setattr(controller, "check", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr("exhale.update_controller.time.time", lambda: 200000)
    controller.check_if_due()
    assert calls == [{"manual": False}]
    calls.clear()
    window.settings.setValue(updates.LAST_CHECK_KEY, 199999)
    controller.check_if_due()
    assert calls == []
    window.settings.setValue(updates.LAST_CHECK_KEY, 0)
    window.settings.setValue(updates.AUTOMATIC_CHECKS_KEY, False)
    controller.check_if_due()
    assert calls == []


def test_update_preference_persists_and_manual_check_remains_available(window, monkeypatch):
    dialog = SettingsDialog(window.settings, window)
    assert dialog.automaticUpdatesCheckBox.isChecked()
    dialog.automaticUpdatesCheckBox.setChecked(False)
    dialog.accept()
    assert not window.settings.value(updates.AUTOMATIC_CHECKS_KEY, True, type=bool)
    reopened = SettingsDialog(window.settings, window)
    assert not reopened.automaticUpdatesCheckBox.isChecked()
    calls = []
    monkeypatch.setattr(window.update_controller, "check", lambda: calls.append("manual"))
    reopened.checkUpdatesButton.click()
    assert calls == ["manual"]
    reopened.reject()


def test_cancelled_window_close_discards_staged_update(window, tmp_path, monkeypatch):
    controller = window.update_controller
    monkeypatch.setattr(type(controller), "state_directory", property(lambda _self: tmp_path))
    monkeypatch.setattr(window, "close", lambda: False)

    class Message:
        AcceptRole = QtWidgets.QMessageBox.AcceptRole
        Close = QtWidgets.QMessageBox.Close

        def __init__(self, *_args):
            self.update = object()

        def setWindowTitle(self, *_args):
            pass

        def setText(self, *_args):
            pass

        def setInformativeText(self, *_args):
            pass

        def addButton(self, text, *_args):
            return self.update if text == "Update now" else None

        def exec(self):
            pass

        def clickedButton(self):
            return self.update

    monkeypatch.setattr("exhale.update_controller.QtWidgets.QMessageBox", Message)
    controller._manual = True
    controller._checked({"version": "2.0", "installation": {"uv": "unused"}, "error": ""})
    assert controller.pending_job is None
    assert not list(tmp_path.glob("update-*"))
