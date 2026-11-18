"""Splitter initialization behavior that depends on realized widget geometry."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from qtpy import QtCore, QtTest, QtWidgets

from exhale.widgets import ContentDoubleSpinBox, IconCheckDelegate, initialize_splitter_on_show


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
        initializer = initialize_splitter_on_show(splitter, splitter, (1, 1, 2))
        initializer.initialize()

        available = splitter.width() - 2 * splitter.handleWidth()
        quarter = round(available / 4)
        self.assertEqual(splitter.sizes(), [quarter, quarter, available - 2 * quarter])

    def test_saved_state_replaces_default_proportions(self):
        source = self.make_splitter()
        source.setSizes((100, 250, 450))
        saved_state = source.saveState()

        restored = self.make_splitter()
        initializer = initialize_splitter_on_show(restored, restored, (1, 1, 2), saved_state)
        initializer.initialize()

        self.assertEqual(restored.sizes(), source.sizes())

    def test_saved_state_with_collapsed_pane_uses_default_proportions(self):
        source = self.make_splitter()
        source.setSizes((0, 250, 450))
        self.assertEqual(source.sizes()[0], 0)
        saved_state = source.saveState()

        restored = self.make_splitter()
        initializer = initialize_splitter_on_show(restored, restored, (1, 1, 2), saved_state)
        initializer.initialize()

        available = restored.width() - 2 * restored.handleWidth()
        quarter = round(available / 4)
        self.assertEqual(restored.sizes(), [quarter, quarter, available - 2 * quarter])


class SpinBoxSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_width_stays_stable_while_typing_and_deleting(self):
        host = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(host)
        spin = ContentDoubleSpinBox()
        spin.setRange(-1000, 1000)
        spin.setDecimals(2)
        layout.addWidget(spin)
        host.show()
        self.app.processEvents()
        self.addCleanup(host.close)
        width = spin.width()
        for value in (-1000, 0, 3, 999):
            spin.setValue(value)
            self.app.processEvents()
            self.assertEqual(spin.width(), width)
        spin.setFocus()
        spin.selectAll()
        QtTest.QTest.keyClick(spin, QtCore.Qt.Key.Key_Backspace)
        self.app.processEvents()
        self.assertEqual(spin.width(), width)
        QtTest.QTest.keyClicks(spin, "-12.5")
        self.app.processEvents()
        self.assertEqual(spin.width(), width)
        self.assertGreaterEqual(
            spin.lineEdit().width(), spin.fontMetrics().horizontalAdvance("-1000.00") + 4
        )

    def test_width_follows_configured_digits_precision_and_font(self):
        spin = ContentDoubleSpinBox()
        spin.setRange(-1000, 1000)
        width = spin.sizeHint().width()
        spin.setRange(-1000000, 1000000)
        self.assertGreater(spin.sizeHint().width(), width)
        width = spin.sizeHint().width()
        spin.setDecimals(4)
        self.assertGreater(spin.sizeHint().width(), width)
        width = spin.sizeHint().width()
        font = spin.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        spin.setFont(font)
        self.assertGreater(spin.sizeHint().width(), width)


if __name__ == "__main__":
    unittest.main()


class ElementDoubleClickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_label_double_click_cycles_tristate(self):
        view = QtWidgets.QListWidget()
        self.addCleanup(view.close)
        view.setItemDelegate(IconCheckDelegate(view))
        item = QtWidgets.QListWidgetItem("Iron")
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserTristate)
        item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        view.addItem(item)
        view.show()
        self.app.processEvents()
        position = view.visualItemRect(item).center()
        for expected in (
            QtCore.Qt.CheckState.PartiallyChecked,
            QtCore.Qt.CheckState.Checked,
            QtCore.Qt.CheckState.Unchecked,
        ):
            QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=position)
            QtTest.QTest.mouseDClick(view.viewport(), QtCore.Qt.LeftButton, pos=position)
            self.assertEqual(item.checkState(), expected)
