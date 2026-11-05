"""Reviewed training exports preserve source values, instance IDs and project state."""

import json
from unittest.mock import patch

import h5py
import numpy as np
import pytest
from tifffile import imread

from exhale.analysis import trainingio
from exhale.data.projectdata import ProjectData, SegmentationResult
from exhale.data.segmentation import (
    SegmentationOutput,
    SegmentationParameters,
    SegmentationPostprocessing,
)
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.source_refs import open_source
from exhale.project.projectio import export_project_state


@pytest.fixture
def project(tmp_path):
    project = ProjectData()
    for index in range(3):
        path = tmp_path / f"sample-{index}.h5"
        with h5py.File(path, "w") as f:
            f.attrs["default"] = "entry"
            f.create_dataset(
                "entry/plotselect/P",
                data=np.arange(30, dtype=np.float64).reshape(5, 6) + index / 10,
            )
        project.register_source(open_source(str(path)))
    for index, sample in enumerate(project.samples.values()):
        ref = sample.channels["P"].ref
        labels = np.zeros((5, 6), dtype=np.uint32)
        labels[1:3, 2:4] = 70000 + index
        result = SegmentationResult(
            sample.sample_id,
            "stardist",
            ref,
            SegmentationParameters(clip_percentile=99.9, method_options={"setting": 2}),
            SegmentationOutput(labels, "trained-model", "v1"),
            postprocessing=SegmentationPostprocessing(100),
        )
        project.set_segmentation_result(result)
        history = project.segmentation_histories[sample.sample_id]
        if index < 2:
            history.set_reviewed(history.active_id)
    yield project
    for source in project.sources.values():
        source.close()


def test_export_uses_reviewed_raw_labels_not_active_mask_postprocessing_or_draft(project, tmp_path):
    reviewed = trainingio.reviewed_candidates(project)
    for original in reviewed:
        history = project.segmentation_histories[original.sample_id]
        labels = np.ones((5, 6), dtype=np.uint32)
        project.set_segmentation_result(
            SegmentationResult(
                original.sample_id,
                "cellpose",
                original.result.input_ref,
                SegmentationParameters(),
                SegmentationOutput(labels, "different-model", "v2"),
            )
        )
        assert history.active is not original and history.reviewed is original
        session = SegmentationEditSession(original)
        session.apply_labels(labels)
        project.segmentation_edit_sessions[original.sample_id] = session
        assert not original.result.processed_labels.any()
    before = export_project_state(project, tmp_path)
    destination = tmp_path / "training"
    assert trainingio.export_training_data(project, destination) == 2
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["source_values"] == "raw"
    assert manifest["abundance_units"] == project.abundance_units
    assert manifest["pixel_resolution"] == project.image_defaults.resolution
    assert len(manifest["samples"]) == 2
    for record in manifest["samples"]:
        history = project.segmentation_histories[record["sample_id"]]
        candidate = history.reviewed
        channel = project.samples[candidate.sample_id].channels["P"]
        image = imread(destination / record["image"])
        labels = imread(destination / record["mask"])
        np.testing.assert_array_equal(image, channel.data_source.backing[()])
        assert image.dtype == np.float64
        np.testing.assert_array_equal(labels, candidate.result.output.labels)
        assert labels.dtype == np.uint32
        assert record["candidate_id"] == candidate.candidate_id
        assert record["reviewed_revision"] == record["revision_id"] == candidate.revision_id
        assert record["source_ref"] == channel.ref.to_json()
        assert record["runs"][0]["input_ref"] == channel.ref.to_json()
        assert record["runs"][0]["model_id"] == "trained-model"
        assert record["parameters"]["clip_percentile"] == 99.9
        assert not channel.data_source.has_cache
    assert export_project_state(project, tmp_path) == before


def test_export_never_overwrites_an_existing_directory(project, tmp_path):
    destination = tmp_path / "training"
    destination.mkdir()
    marker = destination / "important.txt"
    marker.write_text("keep")
    with pytest.raises(FileExistsError):
        trainingio.export_training_data(project, destination)
    assert marker.read_text() == "keep" and list(destination.iterdir()) == [marker]


def test_missing_source_cleans_partial_output_and_keeps_reviewed_objects(project, tmp_path):
    candidates = trainingio.reviewed_candidates(project)
    bad = candidates[-1]
    project.sources[bad.result.input_ref.source_id].close()
    destination = tmp_path / "training"
    with pytest.raises(ValueError, match="Cannot export sample"):
        trainingio.export_training_data(project, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".exhale-training-*"))
    assert trainingio.reviewed_candidates(project) == candidates


def test_failed_write_cleans_partial_output_and_releases_new_source_cache(project, tmp_path):
    destination = tmp_path / "training"
    with patch.object(trainingio, "imwrite", side_effect=OSError("disk full")):
        with pytest.raises(ValueError, match="disk full"):
            trainingio.export_training_data(project, destination)
    assert not destination.exists() and not list(tmp_path.glob(".exhale-training-*"))
    for sample in project.samples.values():
        assert not sample.channels["P"].data_source.has_cache


def test_empty_review_selection_writes_nothing(project, tmp_path):
    for history in project.segmentation_histories.values():
        if history.reviewed is not None:
            history.set_reviewed(history.reviewed.candidate_id, False)
    with pytest.raises(ValueError, match="No masks"):
        trainingio.export_training_data(project, tmp_path / "training")
    assert not (tmp_path / "training").exists()
