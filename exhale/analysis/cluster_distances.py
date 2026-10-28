"""Directed cluster distances and pooled-mask random-placement statistics."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class ClusterDistanceMatrix:
    """Mean directed nearest-centroid distances for a sample's elements."""

    labels: tuple[str, ...]
    keys: tuple[str, ...]
    values: np.ndarray
    variances: np.ndarray
    standard_deviations: np.ndarray
    counts: np.ndarray
    units: str
    normalized: bool = False
    random_expectations: np.ndarray | None = None
    percentile: bool = False
    simulations: int = 0


@dataclass(frozen=True)
class RandomPlacementStatistics:
    """Null distribution summaries for a complete directed distance matrix."""

    means: np.ndarray
    variances: np.ndarray
    standard_deviations: np.ndarray
    counts: np.ndarray
    simulations: int
    percentiles: np.ndarray | None = None


def _cluster_support(cluster_masks: tuple[np.ndarray, ...]) -> np.ndarray:
    """Return the unexpanded union of the supplied cluster masks."""
    support = None
    for mask in cluster_masks:
        mask = np.asarray(mask)
        if mask.ndim != 2:
            raise ValueError("Cluster label images must be two-dimensional")
        if support is None:
            support = np.zeros(mask.shape, dtype=bool)
        elif mask.shape != support.shape:
            raise ValueError("Cluster label images must have equal dimensions")
        support |= mask > 0
    if support is None or not np.any(support):
        raise ValueError("The segmented elements contain no cluster regions")
    return support


def _random_distance_matrix(point_sets: tuple[np.ndarray, ...]) -> np.ndarray:
    """Calculate one directed nearest-distance matrix in pixel units."""
    size = len(point_sets)
    values = np.full((size, size), np.nan, dtype=np.float64)
    trees = tuple(cKDTree(points) if len(points) else None for points in point_sets)
    for row, source in enumerate(point_sets):
        if not len(source):
            continue
        for column, tree in enumerate(trees):
            if tree is None:
                continue
            if row == column:
                if len(source) < 2:
                    continue
                distances, _indices = tree.query(source, k=2)
                distances = distances[:, 1]
            else:
                distances, _indices = tree.query(source, k=1)
            values[row, column] = float(np.mean(distances))
    return values


def random_placement_statistics(
    counts,
    cluster_masks: tuple[np.ndarray, ...],
    *,
    simulations: int = 1000,
    observed: np.ndarray | None = None,
    seed: int = 0,
    cancelled: Callable[[], bool] | None = None,
) -> RandomPlacementStatistics:
    """Simulate complete distance matrices within the union of cluster masks.

    Each element receives an independently randomized centroid set with its
    observed cluster count. Centroids do not share a support pixel within one
    element, but sets belonging to different elements may overlap. If observed
    distances (in pixels) are supplied, percentiles count simulated means strictly
    below each observation; unavailable cells remain NaN.
    """
    raw_counts = np.asarray(counts)
    if raw_counts.ndim != 1:
        raise ValueError("Cluster counts must be one-dimensional")
    if np.issubdtype(raw_counts.dtype, np.integer):
        counts = raw_counts.astype(np.int64, copy=True)
    else:
        try:
            finite = np.isfinite(raw_counts)
        except TypeError as error:
            raise ValueError("Cluster counts must be non-negative integers") from error
        if not np.all(finite) or not np.all(raw_counts == np.floor(raw_counts)):
            raise ValueError("Cluster counts must be non-negative integers")
        counts = raw_counts.astype(np.int64)
    if np.any(counts < 0):
        raise ValueError("Cluster counts must be non-negative integers")
    if simulations < 2:
        raise ValueError("At least two random-placement simulations are required")

    support = _cluster_support(cluster_masks)
    available = np.argwhere(support).astype(np.float64)
    largest_count = int(counts.max(initial=0))
    if largest_count > len(available):
        raise ValueError("The cluster support contains fewer pixels than an element has clusters")

    size = len(counts)
    if observed is not None:
        observed = np.asarray(observed, dtype=np.float64)
        if observed.shape != (size, size):
            raise ValueError("Observed distances must match the cluster-count matrix")
    below = np.zeros((size, size), dtype=np.int64)
    means = np.zeros((size, size), dtype=np.float64)
    squared_differences = np.zeros_like(means)
    sample_counts = np.zeros((size, size), dtype=np.int64)
    rng = np.random.default_rng(seed)
    for _iteration in range(simulations):
        if cancelled is not None and cancelled():
            raise CancelledError("Random-placement calculation cancelled")
        point_sets = []
        for count in counts:
            if not count:
                point_sets.append(np.empty((0, 2), dtype=np.float64))
                continue
            indices = rng.choice(len(available), size=int(count), replace=False)
            points = available[indices] + rng.uniform(-0.5, 0.5, size=(int(count), 2))
            point_sets.append(points)
        values = _random_distance_matrix(tuple(point_sets))
        finite = np.isfinite(values)
        if observed is not None:
            below += finite & (values < observed)
        sample_counts[finite] += 1
        difference = values[finite] - means[finite]
        means[finite] += difference / sample_counts[finite]
        squared_differences[finite] += difference * (values[finite] - means[finite])

    means[sample_counts == 0] = np.nan
    variances = np.full_like(means, np.nan)
    estimable = sample_counts >= 2
    variances[estimable] = squared_differences[estimable] / (sample_counts[estimable] - 1)
    percentiles = None
    if observed is not None:
        percentiles = np.full_like(means, np.nan)
        valid = (sample_counts > 0) & np.isfinite(observed)
        percentiles[valid] = 100.0 * below[valid] / sample_counts[valid]
    return RandomPlacementStatistics(
        means,
        variances,
        np.sqrt(variances),
        counts,
        simulations,
        percentiles,
    )


def _centroids(channel) -> np.ndarray:
    table = channel.cluster_df
    if table is None or not {"centroid-0", "centroid-1"}.issubset(table.columns):
        return np.empty((0, 2), dtype=np.float64)
    points = table.loc[:, ("centroid-0", "centroid-1")].to_numpy(dtype=np.float64)
    return points[np.isfinite(points).all(axis=1)]


def cluster_distance_matrix(
    channels: tuple,
    labels: tuple[str, ...],
    keys: tuple[str, ...],
    *,
    resolution: float,
    units: str,
) -> ClusterDistanceMatrix:
    """Compute row-to-column mean nearest-centroid distances in physical units."""
    if not (len(channels) == len(labels) == len(keys)):
        raise ValueError("Channels, labels and keys must have equal lengths")
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("XRF resolution must be positive")

    points = tuple(_centroids(channel) for channel in channels)
    size = len(channels)
    values = np.full((size, size), np.nan, dtype=np.float64)
    variances = np.full((size, size), np.nan, dtype=np.float64)
    counts = np.fromiter((len(item) for item in points), dtype=np.int64, count=size)
    trees = tuple(cKDTree(item) if len(item) else None for item in points)
    for row, source in enumerate(points):
        if not len(source):
            continue
        for column, tree in enumerate(trees):
            if tree is None:
                continue
            if row == column:
                if len(source) < 2:
                    continue
                distances, _indices = tree.query(source, k=2)
                distances = distances[:, 1]
            else:
                distances, _indices = tree.query(source, k=1)
            distances = np.asarray(distances, dtype=np.float64) * resolution
            values[row, column] = float(np.mean(distances))
            if len(distances) >= 2:
                variances[row, column] = float(np.var(distances, ddof=1))
    return ClusterDistanceMatrix(
        labels,
        keys,
        values,
        variances,
        np.sqrt(variances),
        counts,
        units,
    )
