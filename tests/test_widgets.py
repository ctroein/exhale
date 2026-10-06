"""Splitter initialization behavior that depends on realized widget geometry."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from qtpy import QtCore, QtWidgets

from exhale.widgets import initialize_splitter_on_show


class SplitterInitializerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_splitter(self):
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        for _ in range(3):
            splitter.addWidget(QtWidgets.QWidget())
        splitter.resize(800, 200)
        splitter.show()
        self.app.processEvents()
        self.addCleanup(splitter.close)
        return splitter

    def test_three_pane_default_proportions(self):
        splitter = self.make_splitter()
        initializer = initialize_splitter_on_show(
            splitter, splitter, (1, 1, 2))
        initializer.initialize()

        available = splitter.width() - 2 * splitter.handleWidth()
        quarter = round(available / 4)
        self.assertEqual(splitter.sizes(),
                         [quarter, quarter, available - 2 * quarter])

    def test_saved_state_replaces_default_proportions(self):
        source = self.make_splitter()
        source.setSizes((100, 250, 450))
        saved_state = source.saveState()

        restored = self.make_splitter()
        initializer = initialize_splitter_on_show(
            restored, restored, (1, 1, 2), saved_state)
        initializer.initialize()

        self.assertEqual(restored.sizes(), source.sizes())


if __name__ == "__main__":
    unittest.main()
