"""Exclusive Solo viewing preserves checkbox choices, persistence and pooled contexts."""

from weakref import WeakKeyDictionary

import numpy as np
import pytest
from napari.components import ViewerModel
from qtpy import QtWidgets

from exhale import icons
from exhale.analysis.layerwidgets import LayerListWidget
from exhale.analysis.naparihelper import NapariHelper
from exhale.data.projectdata import SegmentationLayerSettings
from exhale.project.projectio import _layer_settings_from_json, _layer_settings_to_json


@pytest.fixture
def layers():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    helper = NapariHelper.__new__(NapariHelper)
    helper.viewer = ViewerModel()
    helper._image_colors = WeakKeyDictionary()
    helper._label_presentations = WeakKeyDictionary()
    helper._label_color_rng = np.random.default_rng(0)
    data = np.ones((8, 8), np.float32)
    background = helper.viewer.add_image(
        data, name="Background", metadata={"exhale_role": helper.BACKGROUND_ROLE}
    )
    items = [
        helper.viewer.add_image(
            data,
            name=name,
            visible=visible,
            blending=helper.BLENDING_NORMAL,
            metadata={helper.LAYER_ID_KEY: name},
        )
        for name, visible in (("Red", True), ("Green", True), ("Blue", False))
    ]
    widget = LayerListWidget()
    widget.set_helper(helper)
    yield helper, items, widget, background
    widget.deleteLater()
    app.processEvents()


def row_for(widget, layer):
    return next(
        widget.itemWidget(widget.item(i))
        for i in range(1, widget.count())
        if widget.itemWidget(widget.item(i)).layer is layer
    )


def test_button_cycles_normal_add_solo_normal_without_changing_visibility_choices(layers):
    helper, items, widget, background = layers
    row = row_for(widget, items[0])
    original = [layer.visible for layer in items]
    row.additive.click()
    assert helper.layer_blending(items[0]) == helper.BLENDING_ADD
    row.additive.click()
    assert helper.layer_blending(items[0]) == helper.BLENDING_SOLO
    assert items[0].blending == helper.BLENDING_NORMAL
    assert [layer.visible for layer in items] == [True, False, False]
    assert [row_for(widget, layer).visible.isChecked() for layer in items] == original
    assert background.visible
    assert row.additive.icon_name == icons.IconName.LAYER_SOLO
    row.additive.click()
    assert helper.layer_blending(items[0]) == helper.BLENDING_NORMAL
    assert [layer.visible for layer in items] == original


def test_transferring_solo_advances_previous_layer_to_normal_and_refreshes_its_icon(layers):
    helper, items, widget, _ = layers
    first, second = [row_for(widget, layer) for layer in items[:2]]
    first.additive.click()
    first.additive.click()
    second.additive.click()
    second.additive.click()
    assert helper.layer_blending(items[0]) == helper.BLENDING_NORMAL
    assert helper.layer_blending(items[1]) == helper.BLENDING_SOLO
    assert [layer.visible for layer in items] == [False, True, False]
    assert first.additive.icon_name == icons.IconName.LAYERS
    assert not first.additive.isChecked() and second.additive.isChecked()
    second.additive.click()
    assert [layer.visible for layer in items] == [True, True, False]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_visibility_checkbox_ends_solo_and_applies_the_requested_toggle(layers, index):
    helper, items, widget, _ = layers
    row = row_for(widget, items[0])
    row.additive.click()
    row.additive.click()
    row_for(widget, items[index]).visible.toggle()
    expected = [True, True, False]
    expected[index] = not expected[index]
    assert [layer.visible for layer in items] == expected
    assert helper.layer_blending(items[0]) == helper.BLENDING_NORMAL
    assert row.additive.icon_name == icons.IconName.LAYERS


def test_enabling_solo_on_a_hidden_layer_and_rebuilding_rows_preserves_checkbox_states(layers):
    helper, items, widget, _ = layers
    row = row_for(widget, items[2])
    row.additive.click()
    row.additive.click()
    assert [layer.visible for layer in items] == [False, False, True]
    widget.rebuild(items[2])
    assert all(row_for(widget, layer).visible.isChecked() for layer in items)
    assert helper.layer_blending(items[2]) == helper.BLENDING_SOLO
    row_for(widget, items[2]).additive.click()
    assert all(layer.visible for layer in items)


def test_saved_solo_retains_hidden_checkbox_choices_and_can_be_restored(layers):
    helper, items, _, _ = layers
    helper.set_layer_blending(items[0], helper.BLENDING_SOLO)
    saved = helper.layer_settings()
    assert saved.layers["Red"].blending == helper.BLENDING_SOLO
    assert saved.layers["Green"].visible and not saved.layers["Blue"].visible
    restored = _layer_settings_from_json(_layer_settings_to_json(saved))
    helper.clear_solo()
    helper.apply_layer_settings(restored)
    assert helper.layer_blending(items[0]) == helper.BLENDING_SOLO
    assert [layer.visible for layer in items] == [True, False, False]
    helper.clear_solo()
    assert [layer.visible for layer in items] == [True, True, False]


def test_partial_base_settings_do_not_cancel_a_comparison_layer_solo(layers):
    helper, items, _, _ = layers
    helper.set_layer_blending(items[2], helper.BLENDING_SOLO)
    saved = helper.layer_settings()
    helper.clear_solo()
    helper.apply_layer_settings(SegmentationLayerSettings(layers={"Blue": saved.layers["Blue"]}))
    helper.apply_layer_settings(
        SegmentationLayerSettings(
            layers={key: value for key, value in saved.layers.items() if key != "Blue"}
        )
    )
    assert helper.layer_blending(items[2]) == helper.BLENDING_SOLO
    assert [layer.visible for layer in items] == [False, False, True]


def test_clearing_a_pooled_view_drops_solo_and_does_not_revive_its_layers(layers):
    helper, items, _, _ = layers
    helper.set_layer_blending(items[0], helper.BLENDING_SOLO)
    helper.set_sample(None)
    assert not helper.user_layers()
    assert not any(layer.visible for layer in items)
    assert helper._solo_layer is None and not helper._solo_visibility


@pytest.mark.parametrize("mode", ["categorical", "mask", "monochrome"])
@pytest.mark.parametrize("solo", [False, True])
def test_image_auto_considers_only_monochrome_labels_including_through_solo(layers, mode, solo):
    helper, items, widget, _ = layers
    for layer in items:
        layer.visible = False
    labels = np.ones((8, 8), np.uint32)
    for name, rgba in (("Red masks", (1, 0, 0, 1)), ("Blue masks", (0, 0, 1, 1))):
        layer = helper.viewer.add_labels(labels, name=name)
        helper.set_label_display(layer, mode, rgba)
    if solo:
        helper.set_layer_blending(items[2], helper.BLENDING_SOLO)
    widget.rebuild()
    row_for(widget, items[2])._set_image_color_option("auto")
    expected = (1, 0, 0, 1) if mode == helper.LABEL_CATEGORICAL else (0, 1, 0, 1)
    np.testing.assert_allclose(helper.image_color(items[2]), expected, atol=1e-4)


def test_label_button_cycles_modes_and_retains_palette_and_base_color(layers):
    helper, _items, widget, _ = layers
    label = helper.viewer.add_labels(np.ones((8, 8), np.uint32), name="Mask")
    helper.set_label_presentation(label, helper.LABEL_CATEGORICAL, "#ff8000", palette_index=4)
    widget.rebuild()
    row = row_for(widget, label)
    initial_color = helper.label_display_mode(label)[1].copy()
    for expected in (helper.LABEL_MASK, helper.LABEL_MONOCHROME, helper.LABEL_CATEGORICAL):
        row.color_button.click()
        mode, color = helper.label_display_mode(label)
        assert mode == expected
        np.testing.assert_allclose(color, initial_color)
        assert helper.label_palette_index(label) == 4
        assert not row._color_dialog.isVisible()


def test_categorical_menu_selects_all_five_palettes_and_marks_current_one(layers):
    helper, _items, widget, _ = layers
    label = helper.viewer.add_labels(
        np.ones((8, 8), np.uint32),
        name="Mask",
        visible=False,
        metadata={helper.LAYER_ID_KEY: "mask"},
    )
    widget.rebuild()
    row = row_for(widget, label)
    for chosen in (4, 0, 2, 1, 3):
        actions = row.color_button.menu().actions()
        assert [action.text() for action in actions] == [f"Palette {i}" for i in range(1, 6)]
        assert all(not action.icon().isNull() for action in actions)
        actions[chosen].trigger()
        assert helper.label_palette_index(label) == chosen
        assert helper.label_display_mode(label)[0] == helper.LABEL_CATEGORICAL
        assert label.visible
        assert [action.isChecked() for action in row.color_button.menu().actions()] == [
            i == chosen for i in range(5)
        ]
        saved = helper.layer_settings()
        identity = helper.layer_identity(label)
        assert saved.layers[identity].palette_index == chosen


@pytest.mark.parametrize("mode", ["mask", "monochrome"])
def test_monochrome_label_menu_matches_images_and_preserves_mode(layers, mode):
    helper, items, widget, _ = layers
    label = helper.viewer.add_labels(np.ones((8, 8), np.uint32), name="Mask")
    helper.set_label_display(label, mode, "#ffffff")
    widget.rebuild()
    row = row_for(widget, label)
    image_row = row_for(widget, items[0])
    assert [action.text() for action in row.color_button.menu().actions()] == [
        action.text() for action in image_row.color_button.menu().actions()
    ]
    for chosen, rgb in (("Red", (1, 0, 0, 1)), ("Green", (0, 1, 0, 1)), ("Blue", (0, 0, 1, 1))):
        next(
            action for action in row.color_button.menu().actions() if action.text() == chosen
        ).trigger()
        current, color = helper.label_display_mode(label)
        assert current == mode
        np.testing.assert_allclose(color, rgb)
