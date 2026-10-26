"""Directed cluster distances and pooled-mask random-placement normalization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import distance_transform_edt
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


def normalize_cluster_distance_matrix(
    matrix: ClusterDistanceMatrix,
    support_channels: tuple,
    *,
    resolution: float,
    simulations: int = 1000,
    expansion: float = 2.0,
    seed: int = 0,
) -> ClusterDistanceMatrix:
    """Normalize distances by random placement in the expanded pooled cluster mask."""
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("XRF resolution must be positive")
    if simulations < 1:
        raise ValueError("At least one random-placement simulation is required")
    if not np.isfinite(expansion) or expansion < 0:
        raise ValueError("Cluster-mask expansion must be non-negative")

    support = None
    for channel in support_channels:
        labels = channel.cluster_labels
        if labels is None:
            continue
        labels = np.asarray(labels)
        if labels.ndim != 2:
            raise ValueError("Cluster label images must be two-dimensional")
        if support is None:
            support = np.zeros(labels.shape, dtype=bool)
        elif labels.shape != support.shape:
            raise ValueError("Cluster label images must have equal dimensions")
        support |= labels > 0
    if support is None or not np.any(support):
        raise ValueError("The segmented elements contain no cluster regions")
    if expansion:
        support = distance_transform_edt(~support) <= expansion

    available = np.argwhere(support).astype(np.float64)
    largest_count = int(matrix.counts.max(initial=0))
    if largest_count > len(available):
        raise ValueError("The cluster support contains fewer pixels than an element has clusters")

    rng = np.random.default_rng(seed)
    cross_expectations = {}
    self_expectations = {}
    for count in np.unique(matrix.counts[matrix.counts > 0]):
        count = int(count)
        cross_total = 0.0
        self_total = 0.0
        for _iteration in range(simulations):
            indices = rng.choice(len(available), size=count, replace=False)
            targets = available[indices] + rng.uniform(-0.5, 0.5, size=(count, 2))
            tree = cKDTree(targets)
            query = available[rng.integers(len(available))] + rng.uniform(-0.5, 0.5, size=2)
            cross_total += float(tree.query(query, k=1)[0])
            if count >= 2:
                distances, _indices = tree.query(targets, k=2)
                self_total += float(np.mean(distances[:, 1]))
        cross_expectations[count] = cross_total / simulations
        if count >= 2:
            self_expectations[count] = self_total / simulations

    expected = np.full(matrix.values.shape, np.nan, dtype=np.float64)
    for row in range(len(matrix.counts)):
        for column, count in enumerate(matrix.counts):
            count = int(count)
            if row == column:
                expected[row, column] = self_expectations.get(count, np.nan)
            elif count:
                expected[row, column] = cross_expectations[count]
    expected *= resolution
    finite = np.isfinite(expected) & (expected > 0)
    values = np.full_like(matrix.values, np.nan)
    variances = np.full_like(matrix.variances, np.nan)
    values[finite] = matrix.values[finite] / expected[finite]
    variances[finite] = matrix.variances[finite] / np.square(expected[finite])
    return ClusterDistanceMatrix(
        matrix.labels,
        matrix.keys,
        values,
        variances,
        np.sqrt(variances),
        matrix.counts,
        "",
        normalized=True,
        random_expectations=expected,
    )
