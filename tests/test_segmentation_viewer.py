"""Exact label display, missing-source and per-result presentation contracts."""

from types import SimpleNamespace
from unittest.mock import Mock
from weakref import WeakKeyDictionary

import numpy as np
import pytest
from napari.components import ViewerModel
from qtpy import QtWidgets

from exhale.analysis.controller import AnalysisController
from exhale.analysis.segmentation_viewer import SegmentationViewer
from exhale.data.projectdata import LayerPresentation, SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
)
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate
from exhale.data.source_refs import ElementRef


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def viewer(qt_app):
    helper = SegmentationViewer.__new__(SegmentationViewer)
    helper.viewer = ViewerModel()
    helper.result = None
    helper.input_map = None
    helper.inspection_callback = None
    helper.selection_callback = None
    helper.edit_session = None
    helper._pending_stroke = None
    helper._selection_layers = []
    helper.nuc_layer = None
    helper._image_colors = WeakKeyDictionary()
    helper._label_presentations = WeakKeyDictionary()
    helper._label_color_rng = np.random.default_rng(0)
    helper.info_widget = Mock()
    helper._tt_show = Mock()
    helper._tt_hide = Mock()
    yield helper
    helper.cancel_stroke()
    qt_app.processEvents()


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


def test_comparison_masks_are_read_only_and_do_not_replace_active_inspection(viewer):
    active = result([[0, 1], [0, 0]])
    other = SegmentationCandidate.from_result(result([[0, 42], [42, 42]]))
    other.compare = True
    other.comparison_presentation = LayerPresentation(
        False, 0.3, "translucent_no_depth", (1, 1, 0, 1), viewer.LABEL_MASK, 0
    )
    viewer.set_result(active, comparisons=[(other, "Other mask")])
    comparison = next(
        layer for layer in viewer.user_layers() if "exhale_comparison_id" in layer.metadata
    )
    assert not comparison.editable and not comparison.visible and comparison.opacity == 0.3
    np.testing.assert_array_equal(comparison.data, other.result.processed_labels)
    assert viewer.result is active
    assert viewer._label_at(SimpleNamespace(position=(1, 1))) == (1, 1, 0)
    viewer.set_result(active, comparisons=[(other, "Other mask")], fit=False)
    assert comparison in viewer.user_layers()
    viewer.set_result(other.result, fit=False)
    assert comparison not in viewer.viewer.layers
    assert viewer.result is other.result


def test_edit_selection_outlines_preserve_labels_and_screen_width(viewer):
    candidate = SegmentationCandidate.from_result(result([[0, 42, 42], [7, 0, 7]]))
    session = SegmentationEditSession(candidate)
    session.select(42)
    session.select(7, toggle=True)
    viewer.set_result(candidate.result, edit_session=session)
    assert len(viewer._selection_layers) == 2
    assert all(layer.visible and not layer.editable for layer in viewer._selection_layers)
    assert all(layer not in viewer.user_layers() for layer in viewer._selection_layers)
    np.testing.assert_array_equal(viewer.nuc_layer.data, candidate.result.output.labels)
    camera = getattr(viewer.viewer, "scene", viewer.viewer).camera
    camera.zoom = 4
    viewer._selection_zoom()
    for layer, width in zip(viewer._selection_layers, (3, 1), strict=True):
        np.testing.assert_allclose(np.asarray(layer.edge_width) * camera.zoom, width)
    viewer.set_result(candidate.result, fit=False)
    assert not any(layer.visible for layer in viewer._selection_layers)
    assert not session.changed


def test_native_control_modifier_toggles_selection(viewer):
    from vispy.util.keys import CONTROL

    candidate = SegmentationCandidate.from_result(result([[0, 42], [7, 0]]))
    session = SegmentationEditSession(candidate)
    viewer.selection_callback = Mock()
    viewer.set_result(candidate.result, edit_session=session)
    viewer._click(
        None, SimpleNamespace(position=(0, 1), type="mouse_press", button=1, modifiers=(CONTROL,))
    )
    viewer.selection_callback.assert_called_once_with(42, True, position=(0, 1))


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


def test_brush_drag_previews_then_commits_once_and_cancel_restores_labels(viewer):
    labels = np.zeros((12, 15), dtype=np.uint32)
    labels[3:6, 3:6] = 42
    candidate = SegmentationCandidate.from_result(result(labels))
    session = SegmentationEditSession(candidate)
    session.select(42)
    viewer.set_result(candidate.result, edit_session=session)
    viewer.set_edit_tool("add")
    commits = []

    def edit(tool, points, *, preview=False):
        if preview:
            return session.preview_brush_stroke(points, size=3)
        commits.append(tool)
        session.brush_stroke(points, size=3)
        return session.labels

    viewer.edit_callback = edit
    event = SimpleNamespace(position=(4, 5), button=1, type="mouse_press")
    drag = viewer._edit_drag(None, event)
    next(drag)
    event.type = "mouse_move"
    event.position = (4, 10)
    next(drag)
    assert not session.can_undo and not session.changed
    assert viewer.nuc_layer.data[4, 9] == 42
    event.type = "mouse_release"
    with pytest.raises(StopIteration):
        next(drag)
    QtWidgets.QApplication.processEvents()
    assert commits == ["brush"] and session.can_undo
    session.undo()
    assert not session.can_undo
    np.testing.assert_array_equal(session.labels, labels)

    event.type = "mouse_press"
    drag = viewer._edit_drag(None, event)
    next(drag)
    viewer.cancel_stroke()
    event.type = "mouse_release"
    with pytest.raises(StopIteration):
        next(drag)
    QtWidgets.QApplication.processEvents()
    assert commits == ["brush"] and not session.changed
    np.testing.assert_array_equal(viewer.nuc_layer.data, labels)
    viewer.set_result(candidate.result)
    camera = getattr(viewer.viewer, "scene", viewer.viewer).camera
    assert camera.mouse_pan


@pytest.mark.parametrize(
    "modifier, expected", [("shift", "outline_add"), ("control", "outline_remove")]
)
def test_outline_modifier_selects_operation_for_the_whole_gesture(viewer, modifier, expected):
    from vispy.util.keys import CONTROL, SHIFT

    candidate = SegmentationCandidate.from_result(result([[42, 42], [42, 42]]))
    session = SegmentationEditSession(candidate)
    viewer.set_result(candidate.result, edit_session=session)
    viewer.set_edit_tool("draw")
    viewer.edit_callback = Mock(return_value=session.labels)
    event = SimpleNamespace(
        position=(0, 0),
        button=1,
        type="mouse_press",
        modifiers=(SHIFT if modifier == "shift" else CONTROL,),
    )
    drag = viewer._edit_drag(None, event)
    next(drag)
    event.modifiers = ()
    event.type = "mouse_release"
    with pytest.raises(StopIteration):
        next(drag)
    QtWidgets.QApplication.processEvents()
    assert all(call.args[0] == expected for call in viewer.edit_callback.call_args_list)


@pytest.mark.parametrize(
    "tool, button, expected",
    [("add", 1, "add"), ("add", 2, "remove"), ("remove", 1, "remove"), ("remove", 2, "add")],
)
def test_mouse_button_resolves_brush_operation_and_control_does_not_invert(
    viewer, tool, button, expected
):
    from vispy.util.keys import CONTROL

    labels = np.zeros((12, 15), dtype=np.uint32)
    labels[3:6, 3:6] = 42
    session = SegmentationEditSession(SegmentationCandidate.from_result(result(labels)))
    session.select(42)
    viewer.set_result(session.source.result, edit_session=session)
    viewer.set_edit_tool(tool)
    commits = []

    def edit(operation, strokes, *, preview=False):
        assert operation == "brush"
        if preview:
            return session.preview_brush_stroke(strokes, size=1)
        commits.append(strokes)
        session.brush_stroke(strokes, size=1)
        return session.labels

    viewer.edit_callback = edit
    event = SimpleNamespace(
        position=(4, 5), button=button, type="mouse_press", modifiers=(CONTROL,)
    )
    drag = viewer._edit_drag(None, event)
    next(drag)
    event.type = "mouse_move"
    event.position = (4, 9)
    next(drag)
    assert viewer.nuc_layer.data[4, 5] == (42 if expected == "add" else 0)
    assert viewer.nuc_layer.data[4, 8] == (42 if expected == "add" else 0)
    event.type = "mouse_release"
    with pytest.raises(StopIteration):
        next(drag)
    QtWidgets.QApplication.processEvents()
    assert len(commits) == 1 and viewer.edit_tool == tool
    assert [operation for operation, points in commits[0]] == [expected]
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)
    assert not session.can_undo


def test_new_comparison_uses_distinct_monochrome_and_keeps_color_on_refresh(viewer):
    active = result([[0, 1], [0, 0]])
    other = SegmentationCandidate.from_result(result([[0, 42], [42, 42]]))
    viewer.set_result(active, np.ones((2, 2)))
    expected = viewer.automatic_layer_color(include_labels=True).getRgbF()
    viewer.set_result(active, np.ones((2, 2)), comparisons=[(other, "Other")])
    presentation = other.comparison_presentation
    assert presentation.label_mode == viewer.LABEL_MONOCHROME
    np.testing.assert_allclose(presentation.color, expected)
    layer = next(
        layer for layer in viewer.user_layers() if "exhale_comparison_id" in layer.metadata
    )
    mode, color = viewer.label_display_mode(layer)
    assert mode == viewer.LABEL_MONOCHROME
    np.testing.assert_allclose(color, expected)
    viewer.set_result(active, np.ones((2, 2)), comparisons=[(other, "Other")], fit=False)
    assert other.comparison_presentation == presentation
    np.testing.assert_allclose(viewer.label_display_mode(layer)[1], expected)


@pytest.mark.parametrize("has_mask", [False, True])
def test_added_element_uses_auto_color_and_keeps_it_on_refresh(viewer, has_mask):
    active = result([[0, 1], [0, 0]]) if has_mask else None
    source = np.ones((2, 2), np.float32)
    ref = ElementRef("data.h5", "/Fe")
    viewer.set_result(active, source)
    expected = viewer.automatic_layer_color(include_labels=True).getRgbF()
    preview = SimpleNamespace(reference_refs=(), layer_settings=viewer.layer_settings())
    control = SimpleNamespace(
        _display_result=active,
        naparihelper=viewer,
        _reference_refs=lambda: active.reference_refs if has_mask else preview.reference_refs,
        _refresh_reference_choices=Mock(),
        _preview=lambda **kwargs: preview,
        window=SimpleNamespace(
            project_state_manager=Mock(),
            analysisChNuclei=Mock(currentData=Mock(return_value=ElementRef("data.h5", "/P"))),
        ),
    )

    def remember():
        owner = active if has_mask else preview
        owner.layer_settings = viewer.layer_settings()

    def refresh(*args, **kwargs):
        owner = active if has_mask else preview
        viewer.set_result(active, source, [(key, "Fe", source) for key in owner.reference_refs])
        viewer.apply_layer_settings(owner.layer_settings)

    control._layer_settings_changed = remember
    control.show_result = refresh
    control.clear_result_view = refresh
    AnalysisController._set_reference_refs(control, (ref,))
    layer = next(
        layer for layer in viewer.user_layers() if "exhale_reference_ref" in layer.metadata
    )
    np.testing.assert_allclose(viewer.image_color(layer), expected)
    assert layer.blending == viewer.BLENDING_ADD
    refresh()
    np.testing.assert_allclose(viewer.image_color(layer), expected)


def test_edit_commit_can_process_nested_mouse_events_after_drag_is_forgotten(viewer):
    """An edit dialog must not re-enter Napari's still-running drag generator."""
    import warnings

    from napari.utils._proxies import ReadOnlyWrapper
    from napari.utils.interactions import (
        mouse_move_callbacks,
        mouse_press_callbacks,
        mouse_release_callbacks,
    )
    from qtpy import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    labels = np.zeros((6, 6), dtype=np.uint32)
    labels[1:3, 1:3] = 42
    session = SegmentationEditSession(SegmentationCandidate.from_result(result(labels)))
    session.select(42)
    viewer.set_result(session.source.result, edit_session=session)
    viewer.set_edit_tool("add")
    model = viewer.viewer
    model.mouse_drag_callbacks.append(viewer._edit_drag)
    commits = []
    errors = []

    def event(kind, position):
        return ReadOnlyWrapper(
            SimpleNamespace(
                position=position,
                button=1,
                type=kind,
                modifiers=(),
                is_dragging=True,
            )
        )

    def edit(tool, strokes, *, preview=False):
        if preview:
            return session.preview_brush_stroke(strokes, size=1)
        loop = QtCore.QEventLoop()

        def nested_mouse_events():
            try:
                mouse_move_callbacks(model, event("mouse_move", (1, 5)))
                mouse_release_callbacks(model, event("mouse_release", (1, 5)))
            except Exception as exc:
                errors.append(exc)
            finally:
                loop.quit()

        QtCore.QTimer.singleShot(0, nested_mouse_events)
        loop.exec()
        session.brush_stroke(strokes, size=1)
        commits.append(tool)
        return session.labels

    viewer.edit_callback = edit
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        mouse_press_callbacks(model, event("mouse_press", (1, 2)))
        mouse_move_callbacks(model, event("mouse_move", (1, 4)))
        mouse_release_callbacks(model, event("mouse_release", (1, 4)))
        app.processEvents()
    assert not errors
    assert not [warning for warning in emitted if "mouse callback" in str(warning.message)]
    assert not model._mouse_drag_gen and not model._persisted_mouse_event
    assert commits == ["brush"]
    assert session.labels[1, 4] == 42 and session.labels[1, 5] == 0
    assert len(session._undo) == 1


@pytest.mark.parametrize("change", ["cancel", "different_session"])
def test_pending_edit_does_not_commit_after_cancellation_or_mask_switch(viewer, change):
    session = SegmentationEditSession(SegmentationCandidate.from_result(result([[0, 42], [0, 0]])))
    viewer.set_result(session.source.result, edit_session=session)
    callback = viewer.edit_callback = Mock(return_value=session.labels)
    viewer._queue_stroke(session, "draw", [(0, 0), (0, 1), (1, 1)])
    callback.assert_not_called()
    if change == "cancel":
        viewer.cancel_stroke()
    else:
        other = SegmentationEditSession(SegmentationCandidate.from_result(result([[1, 1], [0, 0]])))
        viewer.set_result(other.source.result, edit_session=other)
    QtWidgets.QApplication.processEvents()
    callback.assert_not_called()
    assert viewer._pending_stroke is None
    assert not session.changed and not session.can_undo
    np.testing.assert_array_equal(viewer.nuc_layer.data, viewer.edit_session.labels)


def test_queued_fitted_outline_commits_once_and_displays_the_working_mask(viewer):
    candidate = SegmentationCandidate.from_result(result(np.zeros((8, 8), np.uint32)))
    session = SegmentationEditSession(candidate)
    viewer.set_result(candidate.result, edit_session=session)
    region = np.zeros(session.labels.shape, bool)
    region[2:6, 2:6] = True

    def edit(*_args):
        session.edit_region("draw", region)
        return session.labels

    viewer.edit_callback = Mock(side_effect=edit)
    viewer._queue_stroke(session, "draw", [(1, 1), (1, 6), (6, 6)])
    assert not session.changed
    QtWidgets.QApplication.processEvents()
    viewer.edit_callback.assert_called_once()
    np.testing.assert_array_equal(viewer.nuc_layer.data, session.labels)
    assert session.changed and session.can_undo
    session.undo()
    assert not session.changed and not session.can_undo
