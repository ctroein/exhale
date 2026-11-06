"""Local, deterministic outline fitting on a single nuclei intensity map."""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from skimage.draw import polygon
from skimage.measure import find_contours
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


def _resample_loop(points):
    """Sample a closed pixel boundary at roughly one-pixel arc-length intervals."""
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    distance = np.r_[0, np.cumsum(lengths)]
    count = max(8, int(np.ceil(distance[-1])))
    positions = np.linspace(0, distance[-1], count, endpoint=False)
    return np.column_stack([np.interp(positions, distance, axis) for axis in points.T])


def _closed_displacements(cost, offsets):
    """Find a cyclic minimum-cost path with a penalty for unequal neighboring moves.

    Carry every possible starting state through the same dynamic program and
    include the closing transition, avoiding a seam at an arbitrary first point.
    """
    states = len(offsets)
    transition = 0.2 * (offsets[:, None] - offsets[None, :]) ** 2
    previous = np.full((states, states), np.inf)
    np.fill_diagonal(previous, cost[0])
    parents = np.empty((len(cost), states, states), dtype=np.uint8)
    for index in range(1, len(cost)):
        choices = previous[:, :, None] + transition[None, :, :]
        parents[index] = np.argmin(choices, axis=1)
        previous = np.min(choices, axis=1) + cost[index]
    first, state = np.unravel_index(np.argmin(previous + transition), previous.shape)
    selected = np.empty(len(cost), dtype=int)
    selected[-1] = state
    for index in range(len(cost) - 1, 0, -1):
        selected[index - 1] = parents[index, first, selected[index]]
    displacement = offsets[selected]
    # Penalize bending in the displacement field, without shrinking the original
    # contour: minimize squared change from the path plus squared second differences.
    frequencies = 2 * np.pi * np.fft.rfftfreq(len(displacement))
    penalty = 1 + 2 * (2 - 2 * np.cos(frequencies)) ** 2
    return np.fft.irfft(np.fft.rfft(displacement) / penalty, n=len(displacement))


def _mask_topology(mask):
    """Count foreground components and holes with complementary connectivity."""
    components = ndi.label(mask, np.ones((3, 3)))[1]
    holes = ndi.label(ndi.binary_fill_holes(mask) & ~mask)[1]
    return components, holes


def fit_outline(image, initial, *, max_distance=8, protected=None):
    """Adjust closed outlines toward nearby, outward-facing bright-to-dark edges.

    Search along smoothed contour normals on a Gaussian-smoothed source map.
    Coordinate displacements cyclically, favor staying near the drawing, and
    regularize displacement bending. Preserve components/holes and the hard
    displacement band by reducing a deformation if rasterization changes topology.
    No input arrays are modified. Uninformative data retain the drawn region.
    """
    image, initial = np.asarray(image), np.asarray(initial, dtype=bool)
    if image.ndim != 2 or image.shape != initial.shape or min(image.shape) < 2:
        raise ValueError("Outline fitting needs matching two-dimensional images")
    if not np.isfinite(max_distance) or max_distance <= 0:
        raise ValueError("Adjustment distance must be finite and positive")
    protected = np.zeros(initial.shape, bool) if protected is None else np.asarray(protected, bool)
    if protected.shape != initial.shape:
        raise ValueError("Protected pixels must match the image shape")
    initial = initial & ~protected
    if not initial.any():
        raise ValueError("The initial outline contains no unprotected pixels")
    ys, xs = np.nonzero(initial)
    margin = int(np.ceil(max_distance + 7))
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
    gradients = [
        ndi.gaussian_filter(data, 1.5, order=order, mode="nearest") for order in ((1, 0), (0, 1))
    ]
    seed = initial[bounds]
    outside = ndi.distance_transform_edt(~seed)
    inside = ndi.distance_transform_edt(np.pad(seed, 1))[1:-1, 1:-1]
    signed = outside - inside
    allowed = (outside <= max_distance) & ~protected[bounds]
    core = (inside > max_distance) & allowed
    # Keep fine sampling near the drawing even for a large requested search range.
    offsets = np.unique(
        np.r_[
            np.linspace(-max_distance, max_distance, 33),
            np.linspace(-min(max_distance, 8), min(max_distance, 8), 33),
        ]
    )
    loops = []
    contours = find_contours(np.pad(seed, 1), 0.5, fully_connected="high")
    for contour in contours:
        points = _resample_loop(contour - 1)
        smooth = ndi.gaussian_filter1d(points, 1.5, axis=0, mode="wrap")
        tangent = np.roll(smooth, -1, axis=0) - np.roll(smooth, 1, axis=0)
        normal = np.column_stack((-tangent[:, 1], tangent[:, 0]))
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        sign = ndi.map_coordinates(signed, (points + normal).T, order=1, mode="nearest")
        opposite = ndi.map_coordinates(signed, (points - normal).T, order=1, mode="nearest")
        normal[sign < opposite] *= -1
        locations = points[:, None, :] + offsets[None, :, None] * normal[:, None, :]
        sampled = np.stack(
            [
                ndi.map_coordinates(g, locations.reshape(-1, 2).T, order=1, mode="nearest").reshape(
                    locations.shape[:2]
                )
                for g in gradients
            ],
            axis=-1,
        )
        projected = -np.sum(sampled * normal[:, None, :], axis=-1)
        strength = np.maximum(projected, 0)
        positive = strength[strength > 1e-12]
        if not len(positive):
            loops.append((points, normal, np.zeros(len(points))))
            continue
        scale = max(float(np.percentile(positive, 90)), 1e-12)
        alignment = strength / np.maximum(np.linalg.norm(sampled, axis=-1), 1e-12)
        reward = np.minimum(strength / scale, 1) * alignment**2
        cost = -reward + 0.6 * (offsets[None, :] / max_distance) ** 2
        valid = ((locations >= -0.5) & (locations <= np.array(seed.shape) - 0.5)).all(axis=-1)
        cost[~valid] = np.inf
        displacement = np.clip(_closed_displacements(cost, offsets), -max_distance, max_distance)
        loops.append((points, normal, displacement))
    if not any(np.any(np.abs(displacement) > 1e-9) for _, _, displacement in loops):
        return initial.copy()
    topology = _mask_topology(seed)
    for fraction in (1, 0.5, 0.25, 0.125):
        fitted = np.zeros(seed.shape, bool)
        # Marching-squares contours nest by parity; retain both outer boundaries
        # and holes when converting their displaced loops back into pixels.
        for points, normal, displacement in loops:
            moved = points + (fraction * displacement)[:, None] * normal
            region = np.zeros(seed.shape, bool)
            region[polygon(moved[:, 0], moved[:, 1], seed.shape)] = True
            fitted ^= region
        fitted &= allowed
        fitted[core] = True
        if _mask_topology(fitted) == topology:
            result = initial.copy()
            result[bounds] = fitted
            return result
    return initial.copy()
