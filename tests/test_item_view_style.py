"""Native selection markers and decoration geometry stay consistent across lists."""

from types import SimpleNamespace

import pytest
from qtpy import QtCore, QtGui, QtTest, QtWidgets

from exhale import appearance, icons
from exhale.analysis.layerwidgets import LayerListWidget
from exhale.imaging.listwidgets import ElementListWidget, ImageListWidget
from exhale.widgets import IconCheckDelegate


@pytest.fixture(scope="session")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def views(app):
    original_style = app.style().objectName()
    original_palette = app.palette()
    hints = app.styleHints()
    if app.platformName() != "windows" or "windows11" not in QtWidgets.QStyleFactory.keys():
        pytest.skip("Requires the native Windows 11 style")
    app.setStyle("windows11")
    appearance._install_application_style(app)
    assert isinstance(app.style(), appearance.ItemViewStyle)
    project = QtWidgets.QTreeWidget()
    project.setRootIsDecorated(False)
    project.setItemDelegate(IconCheckDelegate(project))
    project_item = QtWidgets.QTreeWidgetItem(project, ["Fe"])
    project_item.setCheckState(0, QtCore.Qt.Checked)
    sample = ElementListWidget()
    sample.use_sample_check_delegate()
    sample.addSampleChannel("Fe", "Fe", None, "override", deferred=False, project_enabled=True)
    images = ImageListWidget()
    images.addImage(0, SimpleNamespace(name="Image"))
    files = QtWidgets.QTreeWidget()
    root = QtWidgets.QTreeWidgetItem(files, ["Sample"])
    root.setIcon(0, icons.icon(icons.IconName.FOLDER))
    child = QtWidgets.QTreeWidgetItem(root, ["Data file"])
    child.setIcon(0, icons.icon(icons.IconName.FILE))
    root.setExpanded(True)
    relationships = QtWidgets.QListWidget()
    QtWidgets.QListWidgetItem("Sample", relationships).setCheckState(QtCore.Qt.Checked)
    batch = QtWidgets.QTreeWidget()
    QtWidgets.QTreeWidgetItem(batch, ["Sample"]).setCheckState(0, QtCore.Qt.Checked)
    layers = LayerListWidget()
    layers.rebuild()
    QtWidgets.QListWidgetItem("Layer", layers)
    widgets = (project, sample, images, files, relationships, batch, layers)
    for view in widgets:
        view.resize(260, 150)
        if isinstance(view, QtWidgets.QTreeWidget):
            view.setHeaderHidden(True)
            view.setCurrentItem(view.topLevelItem(0))
        else:
            view.setCurrentRow(1 if view is layers else 0)
        view.show()
    app.processEvents()
    yield app, widgets, child
    for view in widgets:
        view.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    hints.unsetColorScheme()
    app.setStyle(original_style)
    app.setPalette(original_palette)


@pytest.mark.parametrize("direction", [QtCore.Qt.LeftToRight, QtCore.Qt.RightToLeft])
@pytest.mark.parametrize("scheme", [QtCore.Qt.ColorScheme.Light, QtCore.Qt.ColorScheme.Dark])
def test_marker_uses_the_same_viewport_edge_in_all_lists(views, direction, scheme):
    app, widgets, child = views
    app.styleHints().setColorScheme(scheme)
    app.setPalette(QtGui.QPalette())
    for view in widgets:
        view.setLayoutDirection(direction)
    app.processEvents()
    markers = []
    for view in (*widgets, widgets[3]):
        if view is widgets[3] and len(markers) == len(widgets):
            view.setCurrentItem(child)
            app.processEvents()
        rect = view.visualRect(view.currentIndex())
        image = view.viewport().grab().toImage()
        accent = view.palette().color(QtGui.QPalette.Accent)
        marker = [
            distance
            for distance in range(8)
            if image.pixelColor(
                distance if direction == QtCore.Qt.LeftToRight else image.width() - distance - 1,
                rect.center().y(),
            )
            == accent
        ]
        assert marker, type(view).__name__
        viewport = view.viewport().geometry()
        margin = (
            viewport.left()
            if direction == QtCore.Qt.LeftToRight
            else view.width() - viewport.right() - 1
        )
        markers.append([position + margin for position in marker])
    assert all(marker == markers[0] for marker in markers)


def test_images_and_files_use_the_same_native_decoration_size(views):
    _app, widgets, child = views
    images, files = widgets[2:4]
    files.setCurrentItem(child)
    sizes, heights = [], []
    for view in (images, files):
        option = QtWidgets.QStyleOptionViewItem()
        view.initViewItemOption(option)
        view.itemDelegate().initStyleOption(option, view.currentIndex())
        sizes.append(option.decorationSize)
        heights.append(view.visualRect(view.currentIndex()).height())
    assert sizes[0] == sizes[1]
    assert sizes[0].width() > 0
    assert heights[0] == heights[1]


def test_image_name_editor_keeps_clear_of_the_marker(views):
    app, widgets, _child = views
    images = widgets[2]
    app.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
    app.setPalette(QtGui.QPalette())
    images.editItem(images.currentItem())
    app.processEvents()
    editor = images.findChild(QtWidgets.QLineEdit)
    assert editor is not None
    assert editor.geometry().left() >= appearance.ItemViewStyle.MARKER_GUTTER
    editor.selectAll()
    QtTest.QTest.keyClicks(editor, "Renamed image")
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Return)
    app.processEvents()
    assert images.currentItem().text() == "Renamed image"
