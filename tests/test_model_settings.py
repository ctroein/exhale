"""Application model locations are independent of projects and launch paths."""

from pathlib import Path

from qtpy import QtCore

from exhale import application_name
from exhale.analysis.model_store import MODEL_DIRECTORY_SETTING
from exhale.model_settings import default_model_directory, model_directory


def test_default_uses_platform_data_location_and_application_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(QtCore.QStandardPaths, "writableLocation", lambda _kind: str(tmp_path))
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    expected = tmp_path / application_name / "models"
    assert default_model_directory() == expected
    assert model_directory(settings) == expected
    assert settings.allKeys() == []
    assert not expected.exists()


def test_explicit_model_directory_is_resolved_without_creating_it(tmp_path):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    chosen = tmp_path / "weights"
    settings.setValue(MODEL_DIRECTORY_SETTING, str(chosen))
    assert model_directory(settings) == chosen
    assert not chosen.exists()
    assert settings.allKeys() == [MODEL_DIRECTORY_SETTING]


def test_user_home_is_expanded(tmp_path):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    settings.setValue(MODEL_DIRECTORY_SETTING, "~/models")
    assert model_directory(settings) == Path.home() / "models"
