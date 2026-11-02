"""Independent segmentation/clustering and partial-result persistence contracts."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from exhale.analysis.segmentationio import load_xrf_sample, save_xrf_sample
from exhale.xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
from exhale.xrf_refcopy.xrf_sample_class import XRFSample


def test_clustering_can_run_without_nuclei_or_tissue_and_preserves_results(tmp_path):
    sample = XRFSample("test")
    image = np.arange(64, dtype=np.float32).reshape(8, 8)
    sample.add_element("Fe", image)
    sample.cluster_elements(min_k=2, max_k=2)
    assert sample.is_clustered
    assert not sample.is_segmented
    assert not sample.is_combined
    assert sample.nuclei is None
    assert sample.tissue is None
    labels = sample.elements["Fe"].cluster_labels
    assert labels is not None

    filename = tmp_path / "clusters.h5"
    save_xrf_sample(sample, filename)
    restored = load_xrf_sample(filename)
    assert restored.is_clustered
    assert not restored.is_segmented
    assert restored.nuclei is None
    assert restored.tissue is None
    np.testing.assert_array_equal(restored.elements["Fe"].cluster_labels, labels)


def test_clustering_preserves_segmentation_but_discards_region_assignments():
    sample = XRFSample("test")
    sample.nuclei = SimpleNamespace(process=Mock(), is_processed=True)
    sample.tissue = SimpleNamespace(process=Mock(), is_processed=True)
    sample.elements["Fe"] = SimpleNamespace(process=Mock(), is_processed=True)
    sample._combined = True
    sample.results_df = object()
    sample._df_nuclei = object()
    sample.cluster_elements(min_k=2, max_k=3)
    sample.nuclei.process.assert_not_called()
    sample.tissue.process.assert_not_called()
    assert sample.is_processed
    assert not sample.is_combined
    assert sample._df_nuclei is None


def test_segmentation_only_round_trip_preserves_stage_readiness(tmp_path):
    image = np.ones((3, 4))
    sample = XRFSample("test")
    sample.nuclei = NucleiChannel(image)
    sample.nuclei.nuclei_labels = np.ones_like(image, dtype=np.int32)
    sample.nuclei.expanded_labels = sample.nuclei.nuclei_labels.copy()
    sample.nuclei.membrane_labels = np.zeros_like(sample.nuclei.nuclei_labels)
    sample.nuclei._processed = True
    sample.tissue = TissueChannel(image)
    sample.tissue.tissue_labels = sample.nuclei.nuclei_labels.copy()
    sample.tissue.tissue_mask = image > 0
    sample.tissue.log_image = image.copy()
    sample.tissue._processed = True
    sample.add_element("Fe", image)
    filename = tmp_path / "segmented.h5"
    save_xrf_sample(sample, filename)
    restored = load_xrf_sample(filename)
    assert restored.is_segmented
    assert not restored.is_clustered
    assert not restored.is_combined
    with pytest.raises(RuntimeError):
        restored.combine()


def test_clustering_worker_never_imports_a_neural_backend():
    import subprocess
    import sys

    code = """
import sys
from types import SimpleNamespace
import numpy as np
from exhale.analysis.analysisworker import ClusteringWorker
es = SimpleNamespace(name="Fe", data=np.arange(64, dtype=np.float32).reshape(8, 8))
worker = ClusteringWorker(None, None, [es], "test", min_k=2, max_k=2)
result = worker.xrf_analysis()
assert result.is_clustered
assert not result.is_segmented
assert not {"tensorflow", "stardist", "torch"}.intersection(sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_segmentation_factory_does_not_import_legacy_xrf_model(monkeypatch):
    from exhale.analysis import segmentation_backends as backends
    from exhale.analysis.segmentationmethods import segmentation_method

    image = np.arange(64, dtype=np.float32).reshape(8, 8)
    labels = np.zeros_like(image, dtype=np.uint32)
    labels[2:4, 2:4] = 1
    monkeypatch.setattr(backends, "segment_stardist", lambda _image, **_kw: labels)
    monkeypatch.setattr(backends, "_stardist_version", lambda _path: "test-version")
    monkeypatch.setattr(
        XRFSample, "__init__", Mock(side_effect=AssertionError("Legacy model used"))
    )
    result = segmentation_method("stardist").create_worker(image).execute()
    np.testing.assert_array_equal(result.labels, labels)
    assert result.model_version == "test-version"
