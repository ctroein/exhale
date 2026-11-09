"""Segmentation input, backend isolation, and Cellpose label contracts."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from exhale.analysis import segmentation_backends as backends
from exhale.analysis.segmentationmethods import segmentation_method


def test_preprocessing_clips_without_changing_raw_map():
    image = np.arange(100, dtype=np.float64).reshape(10, 10)
    original = image.copy()
    result = backends.preprocess_map(image, 90)
    assert result.dtype == np.float32
    assert result.max() == pytest.approx(np.percentile(image, 90))
    np.testing.assert_array_equal(image, original)
    np.testing.assert_array_equal(result[result < result.max()], image[image < result.max()])


def test_preprocessing_handles_constant_and_nonfinite_maps():
    np.testing.assert_array_equal(backends.preprocess_map(np.ones((3, 4)), 99.9), 1)
    image = np.array([[np.nan, np.inf], [-np.inf, 2]])
    result = backends.preprocess_map(image, None)
    np.testing.assert_array_equal(result, [[0, 0], [0, 2]])
    assert np.isnan(image[0, 0])


@pytest.mark.parametrize("percentile", [0, -1, 101])
def test_preprocessing_rejects_invalid_percentiles(percentile):
    with pytest.raises(ValueError, match="percentile"):
        backends.preprocess_map(np.ones((2, 2)), percentile)


def test_missing_checkpoint_never_reaches_cellpose_fallback(monkeypatch, tmp_path):
    runtime = Mock()
    monkeypatch.setattr(backends, "prepare_segmentation_runtime", runtime)
    with pytest.raises(ValueError, match="Cellpose trained model"):
        backends.segment_cellpose(np.ones((2, 2)), model_path=str(tmp_path / "missing"))
    runtime.assert_not_called()


def test_cellpose_uses_training_normalization_and_preserves_label_ids(monkeypatch, tmp_path):
    checkpoint = tmp_path / "weights"
    checkpoint.touch()
    labels = np.array([[0, 7], [7, 0]], dtype=np.int32)
    model = SimpleNamespace(eval=Mock(return_value=(labels, None, None)))
    monkeypatch.setattr(backends, "prepare_segmentation_runtime", lambda: None)
    monkeypatch.setattr(backends, "_cellpose_model", lambda *_args: model)
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    )
    image = np.ones((2, 2), dtype=np.float32)
    result = backends.segment_cellpose(image, model_path=str(checkpoint), min_size=3)
    np.testing.assert_array_equal(result, labels)
    assert result.dtype == np.uint32
    kwargs = model.eval.call_args.kwargs
    assert kwargs["normalize"] == {"normalize": True, "percentile": [0.0, 100.0]}
    assert kwargs["min_size"] == 3


def test_cellpose_worker_keeps_faint_nuclei_without_stardist_filtering(monkeypatch):
    from exhale.data.segmentation import SegmentationParameters

    image = np.arange(64, dtype=np.float32).reshape(8, 8)
    labels = np.zeros_like(image, dtype=np.uint32)
    labels[0, 0] = 1
    segment = Mock(return_value=labels)
    monkeypatch.setattr(backends, "segment_cellpose", segment)
    monkeypatch.setattr(backends, "_digest", lambda _path: "version")
    worker = segmentation_method("cellpose").create_worker(
        image,
        parameters=SegmentationParameters(clip_percentile=90, method_options={"min_size": 1}),
        model_path="weights",
    )
    output = worker.execute()
    np.testing.assert_array_equal(output.labels, labels)
    assert segment.call_args.args[0].max() < image.max()
    assert not hasattr(output, "tissue")
    assert not hasattr(output, "membrane_labels")


def test_segmentation_registry_and_workers_do_not_eagerly_load_backends():
    code = """
import sys
from exhale.analysis.segmentationmethods import SEGMENTATION_METHODS
from exhale.analysis.analysisworker import AnalysisWorker
assert {method.method_id for method in SEGMENTATION_METHODS} == {"stardist", "cellpose", "monai", "smp"}
assert not {"torch", "triton", "tensorflow", "cellpose", "dinov3", "monai"}.intersection(sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


@pytest.mark.parametrize(
    "installed",
    [
        (),
        ("stardist",),
        ("cellpose",),
        ("monai",),
        ("smp",),
        ("stardist", "cellpose"),
        ("stardist", "cellpose", "monai"),
    ],
)
def test_startup_checks_only_selected_backends(monkeypatch, installed):
    from exhale.analysis import segmentationmethods as methods

    required = {
        module
        for method in methods.SEGMENTATION_METHODS
        if method.method_id in installed
        for module in method.required_modules
    }
    monkeypatch.setattr(methods, "find_spec", lambda name: object() if name in required else None)
    imports = []

    def load(name):
        imports.append(name)
        return SimpleNamespace(dinov3_vitl16=lambda: None)

    monkeypatch.setattr(methods, "import_module", load)
    methods.check_installed_backends()
    assert ("stardist.models" in imports) == ("stardist" in installed)
    assert ("cellpose.vit" in imports) == ("cellpose" in installed)
    assert ("monai.networks.nets" in imports) == ("monai" in installed or "smp" in installed)
    assert ("segmentation_models_pytorch" in imports) == ("smp" in installed)


def test_startup_rejects_cellpose_without_dinov3(monkeypatch):
    from exhale.analysis import segmentationmethods as methods

    monkeypatch.setattr(
        methods, "find_spec", lambda name: None if name in ("stardist", "dinov3") else object()
    )
    with pytest.raises(RuntimeError, match="dinov3"):
        methods.check_installed_backends()
