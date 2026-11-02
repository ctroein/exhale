"""Application-level location for downloaded segmentation model files."""

from pathlib import Path

from qtpy import QtCore

from . import application_name
from .analysis.model_store import MODEL_DIRECTORY_SETTING


def default_model_directory() -> Path:
    """Use the platform's per-user data directory, independently of the launcher."""
    return (
        Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation))
        / application_name
        / "models"
    )


def model_directory(settings: QtCore.QSettings) -> Path:
    """Read a model location without changing any saved project state."""
    value = settings.value(MODEL_DIRECTORY_SETTING, "", type=str).strip()
    return Path(value).expanduser().resolve() if value else default_model_directory()
