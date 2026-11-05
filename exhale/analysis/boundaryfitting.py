"""Local, deterministic outline fitting on a single nuclei intensity map."""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from skimage.segmentation import (
    inverse_gaussian_gradient,
    morphological_chan_vese,
    morphological_geodesic_active_contour,
)


@dataclass(frozen=True)
class BoundaryFitParameters:
    """Image smoothing, curvature smoothing and bounded contour evolution settings."""

    method: str = "region"
    iterations: int = 40
    sigma: float = 1.0
    smoothing: int = 1
    max_distance: float = 8.0
    region_weight: float = 1.0
    edge_strength: float = 100.0
    edge_threshold: float = 0.5
    balloon: int = 0

    def __post_init__(self):
        if self.method not in ("edges", "region"):
            raise ValueError("Boundary fitting method must be edges or region")
        for name, minimum in (("iterations", 1), ("smoothing", 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}")
        for name in ("sigma", "max_distance", "region_weight", "edge_strength"):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not np.isfinite(self.edge_threshold) or not 0 < self.edge_threshold < 1:
            raise ValueError("Edge threshold must be between 0 and 1")
        if self.balloon not in (-1, 0, 1):
            raise ValueError("Balloon direction must be -1, 0 or 1")


_LINES = (
    np.eye(3, dtype=bool),
    np.fliplr(np.eye(3, dtype=bool)),
    np.array([[0, 0, 0], [1, 1, 1], [0, 0, 0]], dtype=bool),
    np.array([[0, 1, 0], [0, 1, 0], [0, 1, 0]], dtype=bool),
)


def _curvature(mask, step):
    """Alternate the morphological curvature operators with per-fit state.

    Scikit-image's default curvature operator has a shared alternating cycle.
    Owning that cycle here makes results independent of earlier fits or trials.
    """

    def sup_inf(array):
        return np.logical_or.reduce([ndi.binary_erosion(array, line) for line in _LINES])

    def inf_sup(array):
        return np.logical_and.reduce([ndi.binary_dilation(array, line) for line in _LINES])

    return sup_inf(inf_sup(mask)) if step % 2 == 0 else inf_sup(sup_inf(mask))


def fit_boundary(image, initial, parameters=None, *, protected=None):
    """Fit a region near an approximate outline, returning an owned boolean mask.

    Inputs are source intensities and a filled initial outline of matching shape.
    Evolution stays within max_distance pixels of the initial boundary; protected
    pixels remain excluded. Empty fitted regions are returned as failures rather
    than silently replacing them with the initial outline. No inputs are changed.
    """
    parameters = BoundaryFitParameters() if parameters is None else parameters
    image = np.asarray(image)
    initial = np.asarray(initial, dtype=bool)
    if image.ndim != 2 or image.shape != initial.shape or min(image.shape) < 2:
        raise ValueError("Boundary fitting needs matching two-dimensional images")
    protected = np.zeros(initial.shape, bool) if protected is None else np.asarray(protected, bool)
    if protected.shape != initial.shape:
        raise ValueError("Protected pixels must match the image shape")
    initial = initial & ~protected
    if not initial.any():
        raise ValueError("The initial outline contains no unprotected pixels")
    ys, xs = np.nonzero(initial)
    margin = int(np.ceil(parameters.max_distance + 3 * parameters.sigma + 2))
    low = np.maximum(0, (ys.min() - margin, xs.min() - margin))
    high = np.minimum(image.shape, (ys.max() + margin + 1, xs.max() + margin + 1))
    bounds = tuple(slice(int(a), int(b)) for a, b in zip(low, high, strict=True))
    data = np.array(image[bounds], dtype=float, copy=True)
    finite = np.isfinite(data)
    if not finite.any():
        raise ValueError("No finite intensities near the outline")
    data[~finite] = np.median(data[finite])
    lower, upper = np.percentile(data[finite], (1, 99.9))
    if upper <= lower:
        return initial.copy()
    data = np.clip((data - lower) / (upper - lower), 0, 1)
    seed = initial[bounds]
    allowed = (ndi.distance_transform_edt(~seed) <= parameters.max_distance) & ~protected[bounds]
    core = (
        ndi.distance_transform_edt(np.pad(seed, 1))[1:-1, 1:-1] > parameters.max_distance
    ) & allowed
    step = 0
    first = True

    def constrain(level):
        nonlocal step, first
        level[~allowed] = 0
        level[core] = 1
        if not first:
            for _ in range(parameters.smoothing):
                level[:] = _curvature(level, step)
                step += 1
            level[~allowed] = 0
            level[core] = 1
        first = False

    if parameters.method == "region":
        fitted = morphological_chan_vese(
            ndi.gaussian_filter(data, parameters.sigma),
            parameters.iterations,
            init_level_set=seed,
            smoothing=0,
            lambda1=parameters.region_weight,
            lambda2=1,
            iter_callback=constrain,
        )
    else:
        fitted = morphological_geodesic_active_contour(
            inverse_gaussian_gradient(data, alpha=parameters.edge_strength, sigma=parameters.sigma),
            parameters.iterations,
            init_level_set=seed,
            smoothing=0,
            threshold=parameters.edge_threshold,
            balloon=parameters.balloon,
            iter_callback=constrain,
        )
    result = np.zeros(initial.shape, bool)
    result[bounds] = fitted
    return result
