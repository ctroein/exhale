"""Pure segmentation, cancellation, provenance and atomic persistence contracts."""

import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import h5py
import numpy as np
import pytest

from exhale.analysis import segmentation_backends as backends
from exhale.analysis.analysisworker import AnalysisWorker
from exhale.analysis.segmentationio import load_segmentation, save_segmentation
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters


def test_output_owns_unmodified_instance_labels():
    labels = np.array([[0, 42], [7, 0]], dtype=np.int64)
    output = SegmentationOutput(labels, "model", "version")
    labels[:] = 0
    np.testing.assert_array_equal(output.labels, [[0, 42], [7, 0]])
    assert output.labels.dtype == np.uint32


@pytest.mark.parametrize(
    "labels",
    [
        np.zeros((2, 2, 2), dtype=int),
        np.zeros((0, 2), dtype=int),
        np.array([[-1, 0]], dtype=int),
        np.array([[1.0, 0.0]]),
        np.array([[2**32]], dtype=np.uint64),
    ],
)
def test_invalid_label_images_are_rejected(labels):
    with pytest.raises(ValueError):
        SegmentationOutput(labels, "model", "version")


def test_stardist_adapter_returns_small_faint_instances_unchanged(monkeypatch, tmp_path):
    image = np.arange(16, dtype=np.float32).reshape(4, 4)
    labels = np.zeros_like(image, dtype=np.int32)
    labels[0, 0] = 42
    model = SimpleNamespace(predict_instances=Mock(return_value=(labels, {})))
    monkeypatch.setattr(backends, "prepare_segmentation_runtime", lambda: None)
    monkeypatch.setattr(backends, "_stardist_model", lambda *_args: model)
    monkeypatch.setattr(backends, "_stardist_version", lambda _path: "test")
    utils = ModuleType("csbdeep.utils")
    utils.normalize = lambda data: data / 100
    monkeypatch.setitem(sys.modules, "csbdeep.utils", utils)
    path = tmp_path / "weights.h5"
    path.touch()
    actual = backends.segment_stardist(image, model_path=str(path))
    np.testing.assert_array_equal(actual, labels)
    np.testing.assert_array_equal(model.predict_instances.call_args.args[0], image / 100)


def test_stardist_without_a_model_folder_explicitly_loads_keras_weights(monkeypatch, tmp_path):
    module = ModuleType("stardist.models")
    module.Config2D = Mock(side_effect=lambda **kwargs: kwargs)
    model = SimpleNamespace(keras_model=SimpleNamespace(load_weights=Mock()))
    module.StarDist2D = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "stardist.models", module)
    path = tmp_path / "weights.h5"
    backends._stardist_model.cache_clear()
    try:
        actual = backends._stardist_model(str(path), "test-version")
        assert actual is model
        assert module.StarDist2D.call_args.kwargs == {"name": None, "basedir": None}
        model.keras_model.load_weights.assert_called_once_with(str(path))
        assert model.thresholds == {"prob": pytest.approx(0.479071463157368), "nms": 0.3}
    finally:
        backends._stardist_model.cache_clear()


def test_worker_snapshots_input_and_parameters_and_keeps_model_identity(monkeypatch):
    image = np.arange(16, dtype=np.float32).reshape(4, 4)
    parameters = SegmentationParameters(method_options={"min_size": 20})
    worker = AnalysisWorker(image, method_id="cellpose", parameters=parameters, model_path="model")
    image[:] = -1
    parameters.method_options["min_size"] = 999
    seen = []

    def predict(data, **kwargs):
        seen.append((data.copy(), kwargs))
        return np.ones_like(data, dtype=np.uint32)

    monkeypatch.setattr(backends, "segment_cellpose", predict)
    monkeypatch.setattr(backends, "_digest", lambda _path: "revision")
    output = worker.execute()
    assert output.model_id == "cellpose-dino-xrf"
    assert output.model_version == "sha256:revision"
    np.testing.assert_array_equal(seen[0][0], np.arange(16).reshape(4, 4))
    assert seen[0][1]["min_size"] == 20


def test_backend_shape_mismatch_is_not_published(monkeypatch):
    worker = AnalysisWorker(np.ones((2, 3)), model_path="mock")
    monkeypatch.setattr(
        backends, "segment_stardist", lambda *_args, **_kw: np.ones((3, 2), dtype=int)
    )
    monkeypatch.setattr(backends, "_stardist_version", lambda _path: "version")
    finished, failed = [], []
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)
    worker.run()
    assert not finished
    assert len(failed) == 1 and "shape" in failed[0]


def test_cancelled_inference_never_publishes_partial_labels(monkeypatch):
    worker = AnalysisWorker(np.ones((2, 3)), model_path="mock")

    def predict(data, **_kwargs):
        worker.abort()
        return np.ones_like(data, dtype=np.uint32)

    monkeypatch.setattr(backends, "segment_stardist", predict)
    monkeypatch.setattr(backends, "_stardist_version", lambda _path: "version")
    finished, failed = [], []
    worker.finished.connect(finished.append)
    worker.failed.connect(failed.append)
    worker.run()
    assert not finished
    assert failed == [""]


def test_cancel_before_execution_does_not_load_a_backend(monkeypatch):
    backend = Mock()
    monkeypatch.setattr(backends, "run_segmentation", backend)
    worker = AnalysisWorker(np.ones((2, 3)), model_path="mock")
    worker.abort()
    with pytest.raises(InterruptedError):
        worker.execute()
    backend.assert_not_called()


def test_segmentation_sidecar_contains_only_labels_and_provenance(tmp_path):
    output = SegmentationOutput(np.array([[0, 7], [2, 0]]), "model", "revision")
    path = tmp_path / "result.h5"
    save_segmentation(output, path, method_id="cellpose")
    with h5py.File(path) as handle:
        assert list(handle) == ["labels"]
        assert handle.attrs["model_id"] == "model"
        assert handle.attrs["model_version"] == "revision"
    restored = load_segmentation(path, expected_method_id="cellpose")
    np.testing.assert_array_equal(restored.labels, output.labels)
    assert restored.model_id == output.model_id
    assert restored.model_version == output.model_version
    with pytest.raises(ValueError, match="another method"):
        load_segmentation(path, expected_method_id="stardist")


def test_failed_sidecar_write_preserves_previous_result(monkeypatch, tmp_path):
    path = tmp_path / "result.h5"
    output = SegmentationOutput(np.ones((2, 3), dtype=int), "model", "revision")
    save_segmentation(output, path, method_id="cellpose")
    original = path.read_bytes()
    monkeypatch.setattr(h5py.Group, "create_dataset", Mock(side_effect=OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        save_segmentation(output, path, method_id="cellpose")
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_existing_nested_labels_load_without_the_legacy_model(tmp_path):
    path = tmp_path / "old-layout.h5"
    with h5py.File(path, "w") as handle:
        handle.attrs.update(format="exhale-segmentation", version=1, method_id="stardist")
        handle.create_dataset("nuclei/nuclei_labels", data=np.array([[0, 7], [3, 0]]))
    code = """
import sys
from exhale.analysis.segmentationio import load_segmentation
result = load_segmentation(sys.argv[1], expected_method_id="stardist")
assert result.labels.tolist() == [[0,7],[3,0]]
assert result.model_version == "unknown"
assert not any("xrf_refcopy" in name for name in sys.modules)
assert not {"tensorflow", "torch", "stardist"}.intersection(sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", code, str(path)], check=True, capture_output=True, text=True
    )


def test_segmentation_job_never_imports_the_legacy_model():
    code = """
import sys
import numpy as np
from exhale.analysis import segmentation_backends as backend
from exhale.analysis.analysisworker import AnalysisWorker
backend.segment_stardist = lambda data, **kwargs: np.ones(data.shape, dtype=np.uint32)
backend._stardist_version = lambda path: "revision"
output = AnalysisWorker(np.ones((3,4)), model_path="mock").execute()
assert output.labels.shape == (3,4)
assert not any("xrf_refcopy" in name for name in sys.modules)
assert not {"tensorflow", "torch", "stardist"}.intersection(sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_stardist_thresholds_forwarded_and_defaults_do_not_initialize_backend(
    monkeypatch, tmp_path
):
    defaults = backends.stardist_thresholds()
    assert defaults["prob_thresh"] == pytest.approx(0.479071463157368)
    assert defaults["nms_thresh"] == 0.3
    image = np.ones((2, 2), dtype=np.float32)
    model = SimpleNamespace(predict_instances=Mock(return_value=(image.astype(int), {})))
    monkeypatch.setattr(backends, "prepare_segmentation_runtime", lambda: None)
    monkeypatch.setattr(backends, "_stardist_model", lambda *_args: model)
    monkeypatch.setattr(backends, "_stardist_version", lambda _path: "test")
    utils = ModuleType("csbdeep.utils")
    utils.normalize = lambda data: data
    monkeypatch.setitem(sys.modules, "csbdeep.utils", utils)
    path = tmp_path / "weights.h5"
    path.touch()
    backends.segment_stardist(image, model_path=str(path), prob_thresh=0.6, nms_thresh=0.2)
    assert model.predict_instances.call_args.kwargs == {"prob_thresh": 0.6, "nms_thresh": 0.2}
    with pytest.raises(ValueError, match="thresholds"):
        backends.segment_stardist(image, model_path=str(path), prob_thresh=float("nan"))
