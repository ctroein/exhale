"""Segmentation dispatch, shared input preparation, lazy runtime loading and provenance."""

import hashlib
import json
import os
from functools import lru_cache
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path

import numpy as np

from ..data.segmentation import SegmentationOutput, SegmentationParameters


@lru_cache(maxsize=1)
def prepare_segmentation_runtime() -> None:
    """Load PyTorch's native libraries before TensorFlow without starting a model.

    TensorFlow loaded before Triton can abort on duplicate LLVM registrations.
    PyTorch must also precede TensorFlow to avoid conflicting CUDA runtimes.
    Memory growth allows both frameworks' models to coexist on the GPU.
    Call only when starting segmentation, keeping application startup lazy.
    """
    os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
    if find_spec("torch") is not None:
        import torch  # noqa: F401 -- establish native-library loading order

        if find_spec("triton") is not None:
            import triton  # noqa: F401 -- load its LLVM library before TensorFlow


def preprocess_map(image: np.ndarray, clip_percentile: float | None) -> np.ndarray:
    """Return finite float32 segmentation input without modifying the source map."""
    data = np.array(image, dtype=np.float32, copy=True)
    if data.ndim != 2:
        raise ValueError("Segmentation requires a two-dimensional element map")
    np.nan_to_num(data, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    if clip_percentile is not None:
        if not 0 < clip_percentile <= 100:
            raise ValueError("The clipping percentile must be greater than 0 and at most 100")
        np.minimum(data, np.percentile(data, clip_percentile), out=data)
    return data


@lru_cache(maxsize=1)
def _cellpose_model(filename: str, modified_ns: int, gpu: bool):
    """Reuse the selected checkpoint; a replaced file creates a new model."""
    from cellpose.models import CellposeModel

    return CellposeModel(gpu=gpu, pretrained_model=filename)


def segment_cellpose(
    image: np.ndarray,
    *,
    model_path: str,
    min_size: int = 20,
    flow_threshold: float = 0.4,
    cellprob_threshold: float = 0.0,
    callback=lambda _message: None,
) -> np.ndarray:
    """Return Cellpose instance labels using the supplied fine-tuned checkpoint.

    Normalize over the full input range, matching the training configuration;
    shared percentile clipping has already been applied by the worker.
    """
    path = Path(model_path).expanduser()
    if not model_path or not path.is_file():
        raise ValueError("The Cellpose trained model is unavailable")
    if min_size < 1:
        raise ValueError("Cellpose minimum nucleus area must be positive")
    callback("Loading Cellpose model")
    prepare_segmentation_runtime()
    import torch

    model = _cellpose_model(str(path.resolve()), path.stat().st_mtime_ns, torch.cuda.is_available())
    callback("Segmenting nuclei with Cellpose")
    masks, _, _ = model.eval(
        image,
        batch_size=1,
        channel_axis=None,
        normalize={"normalize": True, "percentile": [0.0, 100.0]},
        min_size=min_size,
        flow_threshold=flow_threshold,
        cellprob_threshold=cellprob_threshold,
    )
    callback("Cellpose segmentation complete")
    labels = np.asarray(masks)
    if labels.shape != image.shape or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("Cellpose returned an invalid instance-label image")
    if np.any(labels < 0):
        raise ValueError("Cellpose returned negative instance labels")
    return labels.astype(np.uint32, copy=False)


@lru_cache(maxsize=8)
def _file_digest(filename: str, modified_ns: int, size: int) -> str:
    """Identify model contents once per file revision, independently of location."""
    with open(filename, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(path: Path) -> str:
    stat = path.stat()
    return _file_digest(str(path), stat.st_mtime_ns, stat.st_size)


def _stardist_directory() -> Path:
    return Path(str(files("exhale").joinpath("resources/models/2D_versatile_fluo_copy")))


def stardist_thresholds() -> dict:
    """Read bundled inference defaults without initializing a neural-network runtime."""
    values = json.loads((_stardist_directory() / "thresholds.json").read_text())
    return {"prob_thresh": float(values["prob"]), "nms_thresh": float(values["nms"])}


def _stardist_version(weights: Path) -> str:
    """Include inference thresholds and architecture as well as network weights."""
    digest = hashlib.sha256()
    for name in ("config.json", "thresholds.json", "weights_best.h5"):
        digest.update(name.encode())
        path = weights if name == "weights_best.h5" else _stardist_directory() / name
        digest.update(_digest(path).encode())
    return "sha256:" + digest.hexdigest()


@lru_cache(maxsize=1)
def _stardist_model(filename: str, version: str):
    """Restore downloaded weights and bundled configuration without creating model files."""
    from stardist.models import Config2D, StarDist2D

    directory = _stardist_directory()
    config = Config2D(**json.loads((directory / "config.json").read_text()))
    model = StarDist2D(config, name=None, basedir=None)
    # CSBDeep's load_weights wrapper silently skips loading when basedir=None.
    model.keras_model.load_weights(filename)
    model.thresholds = json.loads((directory / "thresholds.json").read_text())
    return model


def segment_stardist(
    image: np.ndarray,
    *,
    model_path,
    prob_thresh=None,
    nms_thresh=None,
    callback=lambda _message: None,
) -> np.ndarray:
    """Call StarDist directly, retaining every returned instance and its pixels."""
    for value in (prob_thresh, nms_thresh):
        if value is not None and (not np.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("StarDist thresholds must be between 0 and 1")
    path = Path(model_path).expanduser()
    if not model_path or not path.is_file():
        raise ValueError("The StarDist trained model is unavailable")
    callback("Loading StarDist model")
    prepare_segmentation_runtime()
    from csbdeep.utils import normalize

    model = _stardist_model(str(path.resolve()), _stardist_version(path))
    callback("Segmenting with StarDist")
    labels, _details = model.predict_instances(
        normalize(image), prob_thresh=prob_thresh, nms_thresh=nms_thresh
    )
    callback("StarDist segmentation complete")
    return labels


def run_segmentation(
    method_id: str,
    image: np.ndarray,
    parameters: SegmentationParameters,
    *,
    model_path: str | None = None,
    callback=lambda _message: None,
) -> SegmentationOutput:
    """Run a method on one private map copy and validate its labels and provenance."""
    callback("Preparing segmentation input")
    data = preprocess_map(image, parameters.clip_percentile)
    if method_id == "stardist":
        labels = segment_stardist(
            data, model_path=model_path or "", callback=callback, **parameters.method_options
        )
        model_id = "stardist-2d-versatile-fluo"
        version = _stardist_version(Path(model_path or ""))
    elif method_id == "cellpose":
        labels = segment_cellpose(
            data, model_path=model_path or "", callback=callback, **parameters.method_options
        )
        model_id = "cellpose-dino-xrf"
        version = "sha256:" + _digest(Path(model_path).expanduser().resolve())
    elif method_id == "monai":
        from .segmentation_monai import segment_monai

        labels = segment_monai(
            data, model_path=model_path or "", callback=callback, **parameters.method_options
        )
        model_id = "monai-unet-xrf"
        version = "sha256:" + _digest(Path(model_path).expanduser().resolve())
    elif method_id == "smp":
        from .model_store import SMP_MODEL
        from .segmentation_smp import segment_smp

        labels = segment_smp(
            data, model_path=model_path or "", callback=callback, **parameters.method_options
        )
        model_id = SMP_MODEL.model_id
        version = "sha256:" + _digest(Path(model_path).expanduser().resolve())
    else:
        raise ValueError(f"Unknown segmentation method {method_id!r}")
    if np.asarray(labels).shape != data.shape:
        raise ValueError("Segmentation labels do not match the input map's shape")
    output = SegmentationOutput(labels, model_id, version)
    callback("Segmentation complete")
    return output
