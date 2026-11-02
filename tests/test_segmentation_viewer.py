"""Exact label display, missing-source and per-result presentation contracts."""

from types import SimpleNamespace
from unittest.mock import Mock
from weakref import WeakKeyDictionary

import numpy as np
import pytest
from napari.components import ViewerModel

from exhale.analysis.segmentation_viewer import SegmentationViewer
from exhale.data.projectdata import SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
)
from exhale.data.source_refs import ElementRef


@pytest.fixture
def viewer():
    helper = SegmentationViewer.__new__(SegmentationViewer)
    helper.viewer = ViewerModel()
    helper.result = None
    helper.input_map = None
    helper.inspection_callback = None
    helper.nuc_layer = None
    helper._image_colors = WeakKeyDictionary()
    helper._label_presentations = WeakKeyDictionary()
    helper._label_color_rng = np.random.default_rng(0)
    helper.info_widget = Mock()
    helper._tt_show = Mock()
    helper._tt_hide = Mock()
    return helper


def result(labels, sample_id="sample", method="stardist"):
    return SegmentationResult(
        sample_id,
        method,
        ElementRef("data.h5", "/P"),
        SegmentationParameters(),
        SegmentationOutput(np.asarray(labels, dtype=np.uint32), "model", "version"),
    )


def test_thin_instances_and_pixel_ids_are_displayed_unchanged(viewer):
    saved = result([[0, 1, 0], [0, 0, 70000]])
    source = np.arange(6, dtype=np.float32).reshape(2, 3)
    viewer.set_result(saved, source)
    assert viewer.result is saved
    np.testing.assert_array_equal(viewer.nuc_layer.data, saved.output.labels)
    assert not viewer.nuc_layer.editable
    roles = {layer.metadata["exhale_role"] for layer in viewer.user_layers()}
    assert roles == {"nuclei_raw", "nuclei_labels"}
    np.testing.assert_array_equal(source, np.arange(6).reshape(2, 3))
    assert viewer.is_background_layer(viewer.viewer.layers[0])


def test_preview_and_reference_refresh_preserve_input_and_presentation(viewer):
    source = np.arange(6).reshape(2, 3)
    ref = ElementRef("data.h5", "/Fe")
    viewer.set_result(None, source, [(ref, "Fe", source / 5)])
    assert viewer.result is None and viewer.nuc_layer is None
    assert len(viewer.user_layers()) == 2
    reference = next(
        layer for layer in viewer.user_layers() if "exhale_reference_ref" in layer.metadata
    )
    viewer.set_layer_opacity(reference, 30)
    before = viewer.layer_settings()
    viewer.update_reference_maps([(ref, "Fe", source / 10)])
    np.testing.assert_array_equal(reference.data, source / 10)
    np.testing.assert_array_equal(viewer.input_map, source)
    assert viewer.layer_settings() == before
    saved = result([[0, 42, 0], [0, 42, 0]])
    viewer.set_result(saved, source, [(ref, "Fe", source / 10)])
    viewer.apply_layer_settings(before)
    assert reference in viewer.user_layers()
    assert reference.opacity == 0.3
    viewer.set_result(saved, source)
    assert reference not in viewer.user_layers()
    assert len(viewer.user_layers()) == 2


def test_saved_labels_remain_viewable_without_the_source_map(viewer):
    saved = result([[0, 1], [2, 0]])
    viewer.set_result(saved)
    assert viewer.input_map is None
    assert viewer.user_layers() == (viewer.nuc_layer,)
    np.testing.assert_array_equal(viewer.nuc_layer.data, saved.output.labels)


def test_filter_refresh_preserves_all_five_categorical_palettes(viewer):
    saved = result([[0, 1, 2], [3, 4, 5]])
    viewer.set_result(saved)
    layer = viewer.nuc_layer
    ids = np.arange(1, 6)
    palettes = []
    for _ in range(5):
        palettes.append(layer.colormap.map(ids).copy())
        viewer.reseed_label_colormap(layer)
    for index in range(5):
        viewer.set_label_presentation(layer, viewer.LABEL_CATEGORICAL, "red", index)
        state = viewer.layer_settings()
        saved.postprocessing = SegmentationPostprocessing(2)
        viewer.set_result(saved, fit=False)
        viewer.apply_layer_settings(state)
        np.testing.assert_array_equal(layer.colormap.map(ids), palettes[index])
        saved.postprocessing = SegmentationPostprocessing(0)
        viewer.set_result(saved, fit=False)
        viewer.apply_layer_settings(state)
        np.testing.assert_array_equal(layer.colormap.map(ids), palettes[index])


@pytest.mark.parametrize("sample_id, method", [("sample", "cellpose"), ("other", "stardist")])
def test_switching_results_reuses_layers_and_restores_each_presentation(viewer, sample_id, method):
    first = result([[0, 1], [0, 0]])
    second = result([[0, 2], [2, 0]], sample_id=sample_id, method=method)
    source = np.array([[0, 1], [2, 3]], dtype=np.float32)
    viewer.set_result(first, source)
    label_layer = viewer.nuc_layer
    raw_layer = viewer._fixed_layers[viewer.NUCLEI_RAW_ROLE]
    viewer.set_label_display(label_layer, viewer.LABEL_MASK, "red")
    viewer.set_layer_opacity(label_layer, 30)
    viewer.set_layer_gain(raw_layer, 2)
    first.layer_settings = viewer.layer_settings()
    viewer.set_result(second, source)
    viewer.set_label_display(viewer.nuc_layer, viewer.LABEL_MONOCHROME, "blue")
    viewer.set_layer_opacity(viewer.nuc_layer, 80)
    second.layer_settings = viewer.layer_settings()

    for saved in (first, second, first):
        viewer.set_result(saved, source)
        viewer.apply_layer_settings(saved.layer_settings)
        assert viewer.nuc_layer is label_layer
        assert viewer._fixed_layers[viewer.NUCLEI_RAW_ROLE] is raw_layer
        assert viewer.layer_settings() == saved.layer_settings
        np.testing.assert_array_equal(label_layer.data, saved.output.labels)
    assert len(viewer.viewer.layers) == 3


def test_clear_and_missing_source_do_not_modify_saved_labels(viewer):
    saved = result([[0, 1], [2, 0]])
    expected = saved.output.labels.copy()
    viewer.set_result(saved, np.ones((2, 2)))
    viewer.set_result(None)
    assert not viewer.user_layers()
    assert viewer.nuc_layer is None
    assert viewer.result is None
    np.testing.assert_array_equal(saved.output.labels, expected)
    viewer.set_result(saved)
    assert viewer.user_layers() == (viewer.nuc_layer,)
    np.testing.assert_array_equal(viewer.nuc_layer.data, expected)


def test_mismatched_source_shape_cannot_overlay_unrelated_pixels(viewer):
    saved = result([[0, 1], [2, 0]])
    with pytest.raises(ValueError, match="different shapes"):
        viewer.set_result(saved, np.ones((2, 3)))
    assert viewer.result is None


def test_click_and_hover_identify_the_displayed_thin_instance(viewer):
    saved = result([[0, 1, 0], [0, 0, 70000]])
    viewer.set_result(saved)
    event = SimpleNamespace(position=(1, 2), type="mouse_press", button=1)
    viewer._hover(None, event)
    viewer._tt_show.assert_called_once_with("Nucleus: 70000")
    viewer._click(None, event)
    text = viewer.info_widget.setPlainText.call_args.args[0]
    assert "x=2, y=1" in text
    assert "Nucleus: 70000" in text
    assert "Nucleus size: 1 px" in text
    assert "Membrane" not in text


def test_pointer_lookup_matches_napari_pixel_centers(viewer):
    viewer.set_result(result([[0, 1, 0], [0, 0, 70000]]))
    event = SimpleNamespace(position=(0.8, 1.8))
    assert viewer._label_at(event) == (1, 2, 70000)
    event.position = (-0.8, 1.8)
    assert viewer._label_at(event) is None
