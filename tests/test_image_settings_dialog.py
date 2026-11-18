"""Position image settings before the native frame becomes visible."""

import unittest

from qtpy import QtCore, QtWidgets

from exhale.imaging.image_settings_dialog import ImageSettingsDialog


class ImageSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_first_show_positions_before_mapping_and_keeps_user_position(self):
        parent = QtWidgets.QWidget()
        parent.resize(900, 600)
        parent.move(150, 100)
        parent.show()
        self.app.processEvents()
        visible_moves = []

        class ObservedDialog(ImageSettingsDialog):
            def moveEvent(self, event):
                if self.isVisible():
                    visible_moves.append(event.pos())
                super().moveEvent(event)

        dialog = ObservedDialog(parent)
        try:
            dialog.show()
            self.app.processEvents()
            self.assertTrue(dialog.isVisible())
            self.assertEqual(visible_moves, [])
            self.assertTrue(parent.frameGeometry().contains(dialog.frameGeometry().center()))
            dialog.hide()
            chosen_position = parent.pos() + QtCore.QPoint(40, 40)
            dialog.move(chosen_position)
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.pos(), chosen_position)
        finally:
            dialog.deleteLater()
            parent.deleteLater()
            self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
