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
    sizes = []
    native = QtWidgets.QStyleFactory.create("windows11")
    for view in (images, files):
        option = QtWidgets.QStyleOptionViewItem()
        view.initViewItemOption(option)
        view.itemDelegate().initStyleOption(option, view.currentIndex())
        sizes.append(option.decorationSize)
        expected = native.sizeFromContents(
            QtWidgets.QStyle.CT_ItemViewItem, option, QtCore.QSize(), view
        )
        assert view.visualRect(view.currentIndex()).height() == expected.height()
    assert sizes[0] == sizes[1]
    assert sizes[0].width() > 0


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


def test_disabled_light_text_uses_the_native_disabled_field_color(views):
    app, _widgets, _child = views
    app.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
    app.setPalette(QtGui.QPalette())
    native = QtWidgets.QStyleFactory.create("windows11")
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.ButtonText):
        images = []
        for style in (app.style(), native):
            palette = QtGui.QPalette(app.palette())
            if style is native:
                palette.setColor(
                    QtGui.QPalette.Disabled,
                    role,
                    palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text),
                )
            image = QtGui.QImage(150, 35, QtGui.QImage.Format_ARGB32)
            image.fill(palette.color(QtGui.QPalette.Window))
            painter = QtGui.QPainter(image)
            style.drawItemText(
                painter, image.rect(), QtCore.Qt.AlignCenter, palette, False, "Label", role
            )
            painter.end()
            images.append(image)
        assert images[0] == images[1]


def test_disabled_button_border_and_splitter_use_palette_colors(views):
    app, _widgets, _child = views
    app.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
    app.setPalette(QtGui.QPalette())
    option = QtWidgets.QStyleOptionButton()
    option.palette = app.palette()
    option.rect = QtCore.QRect(0, 0, 120, 32)
    image = QtGui.QImage(120, 32, QtGui.QImage.Format_ARGB32)
    image.fill(option.palette.color(QtGui.QPalette.Window))
    painter = QtGui.QPainter(image)
    app.style().drawControl(QtWidgets.QStyle.CE_PushButtonBevel, option, painter)
    painter.end()
    border = option.palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Mid)
    assert any(image.pixelColor(x, y) == border for x in range(120) for y in range(32))
    splitter = QtWidgets.QSplitter()
    try:
        painter = QtGui.QPainter(image)
        app.style().drawControl(QtWidgets.QStyle.CE_Splitter, option, painter, splitter)
        painter.end()
        assert image.pixelColor(60, 16) == app.palette().color(QtGui.QPalette.Base)
    finally:
        splitter.deleteLater()
