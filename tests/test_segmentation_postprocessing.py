"""Reversible area filtering, sparse instance IDs and project reconstruction."""

import h5py
import numpy as np
import pytest

from exhale.analysis.segmentationio import result_relative_path, save_segmentation
from exhale.data.projectdata import ProjectData, SegmentationPreview, SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
    resize_segments,
)
from exhale.data.source_refs import ElementRef, open_source
from exhale.project.projectio import export_project_state, load_project, save_project


def make_result():
    return SegmentationResult(
        "sample",
        "stardist",
        ElementRef("file.h5", "/P"),
        SegmentationParameters(),
        SegmentationOutput(np.array([[0, 42, 42], [2**32 - 1, 0, 42]], dtype=np.uint32), "m", "1"),
    )


def test_filter_boundary_preserves_ids_and_restores_original():
    result = make_result()
    original = result.output.labels.copy()
    result.postprocessing = SegmentationPostprocessing(3)
    expected = original.copy()
    expected[expected == 2**32 - 1] = 0
    np.testing.assert_array_equal(result.processed_labels, expected)
    assert result.processed_labels is result.processed_labels
    assert not result.processed_labels.flags.writeable
    ids, areas = result.segment_areas
    np.testing.assert_array_equal(ids, [42])
    np.testing.assert_array_equal(areas, [3])
    result.postprocessing = SegmentationPostprocessing(4)
    assert not np.any(result.processed_labels)
    assert not len(result.segment_areas[0])
    result.postprocessing = SegmentationPostprocessing(0)
    np.testing.assert_array_equal(result.processed_labels, original)
    np.testing.assert_array_equal(result.output.labels, original)


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_invalid_area_cutoffs_are_rejected(value):
    with pytest.raises(ValueError):
        SegmentationPostprocessing(value)


def test_expansion_precedes_filter_and_cutoff_reuses_resized_labels():
    result = make_result()
    labels = np.zeros((5, 5), dtype=np.uint32)
    labels[2, 2] = 42
    result.output = SegmentationOutput(labels, "m", "1")
    result.postprocessing = SegmentationPostprocessing(5, expansion=1)
    assert np.count_nonzero(result.processed_labels) == 5
    np.testing.assert_array_equal(result.unfiltered_segment_areas[1], [5])
    cached = result.resized_labels
    result.postprocessing = SegmentationPostprocessing(6, expansion=1)
    assert not np.any(result.processed_labels)
    assert result.resized_labels is cached
    result.postprocessing = SegmentationPostprocessing()
    np.testing.assert_array_equal(result.processed_labels, labels)
    np.testing.assert_array_equal(result.output.labels, labels)


def test_expansion_preserves_seeds_and_assigns_each_pixel_at_most_once():
    labels = np.zeros((5, 7), dtype=np.uint32)
    labels[2, 1] = 42
    labels[2, 5] = 2**32 - 1
    expanded = resize_segments(labels, 4)
    assert expanded[2, 1] == 42
    assert expanded[2, 5] == 2**32 - 1
    assert set(np.unique(expanded)) <= {0, 42, 2**32 - 1}
    assert expanded[2, 2] == 42
    assert expanded[2, 4] == 2**32 - 1
    np.testing.assert_array_equal(expanded, resize_segments(labels, 4))


def test_shrinking_erodes_touching_instances_and_image_edges_independently():
    labels = np.full((3, 6), 42, dtype=np.uint32)
    labels[:, 3:] = 2**32 - 1
    expected = np.zeros_like(labels)
    expected[1, 1] = 42
    expected[1, 4] = 2**32 - 1
    np.testing.assert_array_equal(resize_segments(labels, -1), expected)
    assert not np.any(resize_segments(labels, -2))
    assert np.count_nonzero(labels) == 18


@pytest.mark.parametrize("distance", [-3, 0, 3])
def test_resizing_empty_masks_is_empty(distance):
    labels = np.zeros((4, 5), dtype=np.uint32)
    np.testing.assert_array_equal(resize_segments(labels, distance), labels)


def test_project_restores_filter_references_and_untouched_original(tmp_path):
    source_path = tmp_path / "maps.h5"
    with h5py.File(source_path, "w") as f:
        f.attrs["default"] = "entry"
        f.create_dataset("entry/plotselect/P", data=np.ones((2, 3)))
        f.create_dataset("entry/plotselect/Fe", data=np.ones((2, 3)))
    project = ProjectData()
    sample = project.register_source(open_source(str(source_path)))
    result = make_result()
    result.sample_id = sample.sample_id
    result.input_ref = sample.channels["P"].ref
    result.reference_refs = (sample.channels["Fe"].ref,)
    result.postprocessing = SegmentationPostprocessing(3, expansion=1)
    project.set_segmentation_result(result)
    preview = SegmentationPreview(result.input_ref, result.reference_refs)
    project.segmentation_previews[sample.sample_id] = {"cellpose": preview}
    sidecar = tmp_path / result_relative_path(sample.sample_id, "stardist")
    save_segmentation(result.output, sidecar, method_id="stardist")
    before = sidecar.stat().st_mtime_ns
    state_before = export_project_state(project, tmp_path)
    _ = result.processed_labels
    assert export_project_state(project, tmp_path) == state_before
    save_project(project, tmp_path / "project.xhp")
    restored = ProjectData()
    try:
        assert load_project(restored, tmp_path / "project.xhp") == []
        actual = restored.segmentation_result(sample.sample_id, "stardist")
        assert actual.postprocessing == result.postprocessing
        assert actual.reference_refs == result.reference_refs
        restored_preview = restored.segmentation_previews[sample.sample_id]["cellpose"]
        assert restored_preview == preview
        np.testing.assert_array_equal(actual.processed_labels, result.processed_labels)
        np.testing.assert_array_equal(actual.output.labels, result.output.labels)
        assert sidecar.stat().st_mtime_ns == before
    finally:
        for model in (project, restored):
            for source in model.sources.values():
                source.close()
