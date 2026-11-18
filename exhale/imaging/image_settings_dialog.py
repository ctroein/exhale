"""Controller for composed-image settings."""

from qtpy import QtCore, QtWidgets

from .image_settings_dialog_ui import Ui_ImageSettingsDialog


class ImageSettingsDialog(QtWidgets.QDialog, Ui_ImageSettingsDialog):
    """Edit composition settings for an image or the project defaults."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def setVisible(self, visible):
        if (
            visible
            and not self.testAttribute(QtCore.Qt.WA_Moved)
            and self.parentWidget() is not None
        ):
            # Position before Windows maps the native frame, rather than letting
            # the first show correct its position after the frame is visible.
            self.ensurePolished()
            self.adjustSize()
            parent = self.parentWidget()
            position = parent.frameGeometry().center() - self.rect().center()
            available = parent.screen().availableGeometry()
            position.setX(
                max(available.left(), min(position.x(), available.right() - self.width()))
            )
            position.setY(
                max(available.top(), min(position.y(), available.bottom() - self.height()))
            )
            self.move(position)
        super().setVisible(visible)
