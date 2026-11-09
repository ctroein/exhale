"""SMP method options, strict checkpoint loading and shared inference dispatch."""

import os
import subprocess
import sys
from importlib.util import find_spec
from types import SimpleNamespace

import numpy as np
import pytest

from exhale.analysis import segmentation_backends as backends
from exhale.analysis.model_store import SMP_MODEL, model_for_method
from exhale.analysis.segmentation_smp import segment_smp
from exhale.data.segmentation import SegmentationParameters


def test_smp_options_remain_independent_and_do_not_import_neural_backends():
    code = """
import sys
from qtpy import QtWidgets
from exhale.analysis.segmentation_options_dialog import SegmentationOptionsDialog
from exhale.analysis.segmentation_smp import segment_smp
from exhale.data.segmentation import SegmentationParameters
app=QtWidgets.QApplication([])
dialog=SegmentationOptionsDialog()
dialog.set_method('smp')
assert dialog.parameters()==SegmentationParameters(clip_percentile=None,
    method_options={'seed_threshold':.5,'min_size':20})
dialog.set_parameters(SegmentationParameters(clip_percentile=None,
    method_options={'seed_threshold':.7,'min_size':31}))
dialog.set_method('monai')
assert dialog.parameters().method_options=={'seed_threshold':.5,'min_size':20}
dialog.set_method('smp')
assert dialog.parameters().method_options=={'seed_threshold':.7,'min_size':31}
assert not {'torch','tensorflow','monai','segmentation_models_pytorch'}.intersection(sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_API": "pyqt6"},
        check=True,
        capture_output=True,
        text=True,
    )


def test_missing_checkpoint_is_rejected_without_model_construction(tmp_path):
    with pytest.raises(ValueError, match="SMP U-Net trained model"):
        segment_smp(np.ones((4, 5)), model_path=str(tmp_path / "missing.pt"))


def test_dispatch_preserves_labels_and_records_checkpoint_provenance(tmp_path, monkeypatch):
    from exhale.analysis import segmentation_smp as adapter

    path = tmp_path / "weights.pt"
    path.write_bytes(b"checkpoint")
    image = np.arange(30).reshape(5, 6)
    labels = np.zeros(image.shape, np.uint32)
    labels[1:3, 2:4] = 7
    observed = []

    def segment(data, **kwargs):
        observed.append((data.copy(), kwargs))
        return labels

    monkeypatch.setattr(adapter, "segment_smp", segment)
    parameters = SegmentationParameters(
        clip_percentile=None, method_options={"seed_threshold": 0.6, "min_size": 3}
    )
    result = backends.run_segmentation("smp", image, parameters, model_path=str(path))
    np.testing.assert_array_equal(observed[0][0], image)
    np.testing.assert_array_equal(result.labels, labels)
    assert result.model_id == SMP_MODEL.model_id
    assert result.model_version.startswith("sha256:")
    assert observed[0][1]["seed_threshold"] == 0.6
    assert model_for_method("smp") == SMP_MODEL


@pytest.mark.skipif(find_spec("torch") is None, reason="optional PyTorch unavailable")
def test_checkpoint_architecture_and_weights_are_strict_without_encoder_downloads(
    tmp_path, monkeypatch
):
    from exhale.analysis import segmentation_smp as adapter

    backends.prepare_segmentation_runtime()
    import torch

    calls = []

    def network(**kwargs):
        calls.append(kwargs)
        return torch.nn.Conv2d(3, 3, 1)

    monkeypatch.setitem(sys.modules, "segmentation_models_pytorch", SimpleNamespace(Unet=network))
    path = tmp_path / "model.pt"
    state = {
        "network.weight": torch.zeros((3, 3, 1, 1)),
        "network.bias": torch.zeros(3),
        "mean": torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1),
        "std": torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1),
    }
    torch.save({"encoder": "resnet18", "patch_size": 256, "model": state}, path)
    try:
        model, patch_size = adapter._model(str(path), 1, "cpu")
        assert patch_size == 256
        assert calls[0]["encoder_weights"] is None
        assert calls[0]["encoder_name"] == "resnet18"
        assert model(torch.ones((1, 1, 16, 16))).shape == (1, 3, 16, 16)
        torch.save({"encoder": "resnet50", "patch_size": 256, "model": state}, path)
        with pytest.raises(ValueError, match="ResNet18"):
            adapter._model(str(path), 2, "cpu")
        state.pop("network.bias")
        torch.save({"encoder": "resnet18", "patch_size": 256, "model": state}, path)
        with pytest.raises(RuntimeError, match="Missing key"):
            adapter._model(str(path), 3, "cpu")
    finally:
        adapter._model.cache_clear()
