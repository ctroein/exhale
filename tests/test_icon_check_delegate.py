"""Tests for palette-aware item-view checkbox rendering."""

import unittest

from qtpy import QtCore, QtGui, QtTest, QtWidgets

from exhale import icons
from exhale.imaging.listwidgets import ElementListWidget, SampleElementCheckDelegate
from exhale.widgets import IconCheckDelegate


class IconCheckDelegateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.view = QtWidgets.QListWidget()
        self.delegate = IconCheckDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.item = QtWidgets.QListWidgetItem("Channel")
        self.item.setFlags(self.item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        self.item.setCheckState(QtCore.Qt.CheckState.Checked)
        self.view.addItem(self.item)
        self.view.resize(240, 80)
        self.view.show()
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def test_default_icons_cover_all_qt_check_states(self):
        index = self.view.indexFromItem(self.item)
        self.assertEqual(
            self.delegate.indicator_icon_name(index, QtCore.Qt.CheckState.Unchecked),
            icons.IconName.CHECKBOX,
        )
        self.assertEqual(
            self.delegate.indicator_icon_name(index, QtCore.Qt.CheckState.PartiallyChecked),
            icons.IconName.CHECKBOX_DEFAULT_MARKED,
        )
        self.assertEqual(
            self.delegate.indicator_icon_name(index, QtCore.Qt.CheckState.Checked),
            icons.IconName.CHECKBOX_MARKED,
        )

    def test_indicator_uses_svg_native_size(self):
        index = self.view.indexFromItem(self.item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        self.delegate.initStyleOption(option, index)

        self.assertEqual(self.delegate.indicator_rect(option, index).size(), QtCore.QSize(24, 24))

    def test_standard_indicator_click_toggles_model_check_state(self):
        index = self.view.indexFromItem(self.item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.view.visualRect(index)
        option.widget = self.view
        self.delegate.initStyleOption(option, index)

        QtTest.QTest.mouseClick(
            self.view.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=self.delegate.indicator_rect(option, index).center(),
        )

        self.assertEqual(self.item.checkState(), QtCore.Qt.CheckState.Unchecked)

    def test_space_toggles_model_check_state(self):
        self.view.setCurrentItem(self.item)

        QtTest.QTest.keyClick(self.view, QtCore.Qt.Key.Key_Space)

        self.assertEqual(self.item.checkState(), QtCore.Qt.CheckState.Unchecked)

    def test_icon_resolver_can_use_model_roles(self):
        role = QtCore.Qt.ItemDataRole.UserRole + 1
        self.item.setData(role, icons.IconName.CHECKBOX_DENIED)
        delegate = IconCheckDelegate(
            self.view,
            lambda index, _state: index.data(role),
        )
        index = self.view.indexFromItem(self.item)

        self.assertEqual(
            delegate.indicator_icon_name(index, QtCore.Qt.CheckState.Checked),
            icons.IconName.CHECKBOX_DENIED,
        )

    def test_delegate_paints_into_standard_indicator_rect(self):
        image = QtGui.QImage(240, 80, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        index = self.view.indexFromItem(self.item)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.view.visualRect(index)
        option.widget = self.view

        self.delegate.paint(painter, option, index)
        painter.end()

        self.assertFalse(image.isNull())

    def test_sample_delegate_maps_three_states_to_four_glyphs(self):
        view = ElementListWidget()
        self.addCleanup(view.deleteLater)
        view.use_sample_check_delegate()
        delegate = view.itemDelegate()
        self.assertIsInstance(delegate, SampleElementCheckDelegate)

        cases = (
            (
                "inherit",
                True,
                True,
                QtCore.Qt.PartiallyChecked,
                icons.IconName.CHECKBOX_DEFAULT_MARKED,
            ),
            ("skip", True, False, QtCore.Qt.PartiallyChecked, icons.IconName.CHECKBOX),
            ("override", False, True, QtCore.Qt.Checked, icons.IconName.CHECKBOX_MARKED),
            ("skip", False, True, QtCore.Qt.Unchecked, icons.IconName.CHECKBOX_DENIED),
        )
        for row, (state, deferred, project_enabled, check_state, icon_name) in enumerate(cases):
            item = view.addSampleChannel(
                str(row),
                str(row),
                None,
                state,
                deferred=deferred,
                project_enabled=project_enabled,
            )
            index = view.indexFromItem(item)
            self.assertEqual(item.checkState(), check_state)
            self.assertEqual(delegate.indicator_icon_name(index, check_state), icon_name)


if __name__ == "__main__":
    unittest.main()
