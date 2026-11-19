"""Shared item construction preserves native row metrics and list operations."""

from types import SimpleNamespace

import pytest
from qtpy import QtCore, QtWidgets

from exhale import icons
from exhale.imaging.listwidgets import ElementListWidget, ImageListWidget
from exhale.widgets import ItemTreeWidget


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize("style", ["Fusion", "windowsvista", "windows11"])
def test_image_and_file_rows_share_native_geometry(app, style):
    if style.casefold() not in [name.casefold() for name in QtWidgets.QStyleFactory.keys()]:
        pytest.skip("Style unavailable on this platform")
    previous = app.style().objectName()
    app.setStyle(style)
    images, files = ImageListWidget(), ItemTreeWidget()
    try:
        images.addImage(7, SimpleNamespace(name="Image"))
        file_item = QtWidgets.QTreeWidgetItem(files, ["File"])
        file_item.setIcon(0, icons.icon(icons.IconName.FILE))
        for view in (images, files):
            view.resize(240, 100)
            view.show()
        app.processEvents()
        assert (
            images.visualItemRect(images.topLevelItem(0)).height()
            == files.visualItemRect(file_item).height()
        )
        assert images.visualItemRect(images.topLevelItem(0)).left() == 0
        assert files.visualItemRect(file_item).left() == 0
        files.setRootIsDecorated(True)
        child = QtWidgets.QTreeWidgetItem(file_item, ["Child"])
        file_item.setExpanded(True)
        app.processEvents()
        assert files.visualItemRect(child).left() > files.visualItemRect(file_item).left()
        assert images.iconSize() == files.iconSize()
        assert images.indentation() == files.indentation()
        item = images.takeTopLevelItem(0)
        images.insertTopLevelItem(0, item)
        item.setText(0, "Renamed")
        assert item.data(0, ImageListWidget.IMG_NUM_ROLE) == 7
        assert item.text(0) == "Renamed"
        assert item.childCount() == 0
    finally:
        images.deleteLater()
        files.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        app.setStyle(previous)


def test_element_and_image_views_use_shared_native_tree(app):
    for view in (ElementListWidget(), ImageListWidget()):
        try:
            assert isinstance(view, ItemTreeWidget)
            assert view.isHeaderHidden()
            assert not view.rootIsDecorated()
        finally:
            view.deleteLater()
