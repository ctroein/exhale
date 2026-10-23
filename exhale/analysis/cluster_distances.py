"""Directed nearest-centroid distances between segmented element clusters."""

from __future__ import annotations

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
