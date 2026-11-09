"""MONAI U-Net and shared tiled U-Net inference and nucleus-instance conversion."""

from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from skimage.segmentation import relabel_sequential, watershed


def _remove_small_labels(labels, min_size):
    sizes = np.bincount(labels.ravel())
    result = labels.copy()
    result[sizes[labels] < min_size] = 0
    return result


def _validate_options(seed_threshold, min_size):
    """Reject invalid inference options before loading a runtime or allocating labels."""
    if not np.isfinite(seed_threshold) or not 0 <= seed_threshold <= 1:
        raise ValueError("Seed threshold must be between 0 and 1")
    if isinstance(min_size, bool) or not isinstance(min_size, (int, np.integer)) or min_size < 1:
        raise ValueError("Minimum nucleus area must be a positive integer")


def instances_from_probabilities(probabilities, *, seed_threshold=0.5, min_size=20):
    """Watershed background/interior/boundary probabilities once over the whole map.

    Match the supplied model's prediction code, including a distance-maximum
    fallback seed for every foreground component missed by the interior threshold.
    This is model inference postprocessing, independent of editable mask filtering.
    """
    _validate_options(seed_threshold, min_size)
    values = np.asarray(probabilities)
    if (
        values.ndim != 3
        or values.shape[0] != 3
        or min(values.shape[1:]) < 1
        or not np.isfinite(values).all()
        or (values < 0).any()
        or (values > 1).any()
    ):
        raise ValueError("U-Net probabilities must have three finite channels between 0 and 1")
    components, _ = ndi.label((1 - values[0]) > 0.5)
    foreground = _remove_small_labels(components, min_size) > 0
    if not foreground.any():
        return np.zeros(foreground.shape, dtype=np.uint32)
    markers, _ = ndi.label((values[1] > seed_threshold) & foreground)
    markers = _remove_small_labels(markers, 3)
    components, _ = ndi.label(foreground)
    distance = ndi.distance_transform_edt(foreground)
    next_id = int(markers.max()) + 1
    for identity, region in enumerate(ndi.find_objects(components), start=1):
        if region is None:
            continue
        component = components[region] == identity
        if not np.any(markers[region][component]):
            local_distance = np.where(component, distance[region], -1)
            point = np.unravel_index(local_distance.argmax(), component.shape)
            markers[region][point] = next_id
            next_id += 1
    instances = watershed(values[2], markers=markers, mask=foreground)
    return relabel_sequential(_remove_small_labels(instances, min_size))[0].astype(np.uint32)


@lru_cache(maxsize=1)
def _model(filename: str, modified_ns: int, device: str):
    """Reuse the trained residual U-Net until its file or execution device changes."""
    import torch
    from monai.networks.nets import UNet

    model = UNet(
        spatial_dims=2,
        in_channels=1,
        out_channels=3,
        channels=(16, 32, 64, 128),
        strides=(2, 2, 2),
        num_res_units=2,
    )
    model.load_state_dict(torch.load(filename, map_location="cpu", weights_only=True), strict=True)
    return model.to(device).eval()


def segment_monai(
    image, *, model_path, seed_threshold=0.5, min_size=20, callback=lambda _message: None
):
    """Segment with the supplied MONAI residual U-Net checkpoint."""
    path = Path(model_path).expanduser()
    if not model_path or not path.is_file():
        raise ValueError("The MONAI U-Net trained model is unavailable")
    return segment_unet(
        image,
        model_loader=lambda device: (
            _model(str(path.resolve()), path.stat().st_mtime_ns, device),
            256,
        ),
        name="MONAI U-Net",
        seed_threshold=seed_threshold,
        min_size=min_size,
        callback=callback,
    )


def segment_unet(
    image, *, model_loader, name, seed_threshold=0.5, min_size=20, callback=lambda _message: None
):
    """Normalize a clipped map and infer original-size labels with overlapping tiles.

    Blend tile logits before softmax and watershed, matching training inference.
    Use CUDA when available, otherwise CPU; collect logits on CPU. Check the
    worker's cancellation callback before every tile and before instance conversion.
    ``model_loader(device)`` returns the model and its training patch size;
    the model must predict background/interior/boundary logits in that order.
    """
    # Reject invalid controls before loading a neural runtime or model.
    _validate_options(seed_threshold, min_size)
    data = np.array(image, dtype=np.float32, copy=True)
    if data.ndim != 2 or not data.size or not np.isfinite(data).all():
        raise ValueError(f"{name} segmentation needs a finite two-dimensional element map")
    low, high = float(data.min()), float(data.max())
    data -= low
    data /= max(high - low, 1e-6)
    callback(f"Loading {name} model")
    from .segmentation_backends import prepare_segmentation_runtime

    prepare_segmentation_runtime()
    import torch
    from monai.inferers import sliding_window_inference

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, patch_size = model_loader(device)
    tiles = 0

    def predict(inputs):
        nonlocal tiles
        tiles += 1
        callback(f"Segmenting with {name} (tile {tiles})")
        return model(inputs)

    with torch.inference_mode():
        logits = sliding_window_inference(
            torch.from_numpy(data[None, None]),
            roi_size=(patch_size, patch_size),
            sw_batch_size=1,
            predictor=predict,
            overlap=0.5,
            mode="gaussian",
            sw_device=device,
            device="cpu",
        )
        callback(f"Separating {name} nuclei")
        probabilities = logits.softmax(dim=1)[0].numpy()
    labels = instances_from_probabilities(
        probabilities, seed_threshold=seed_threshold, min_size=min_size
    )
    callback(f"{name} segmentation complete")
    return labels
