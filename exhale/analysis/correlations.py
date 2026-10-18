"""Numerical correlation matrices and sample fingerprints."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RegularGridInterpolator


@dataclass(frozen=True)
class CorrelationMatrix:
    """A labelled symmetric matrix with observation counts for each entry."""

    labels: tuple[str, ...]
    keys: tuple[str, ...]
    values: np.ndarray
    counts: np.ndarray


@dataclass(frozen=True)
class SampleSimilarityMatrix:
    """Sample correlations computed from consistently ordered fingerprints."""

    labels: tuple[str, ...]
    sample_ids: tuple[str, ...]
    values: np.ndarray
    counts: np.ndarray
    feature_labels: tuple[str, ...]
    fingerprints: np.ndarray


@dataclass(frozen=True)
class DensityGrid:
    """An irregular, value-positioned two-dimensional density grid."""

    x_edges: np.ndarray
    y_edges: np.ndarray
    density: np.ndarray
    count: int


def _density_edges(values: np.ndarray, bins: int) -> np.ndarray:
    lower = values.min()
    upper = values.max()
    if lower < upper:
        return np.linspace(lower, upper, bins + 1)
    value = float(lower)
    margin = max(abs(value), 1.0) * 0.5
    return np.asarray((value - margin, value + margin))


def density_grid(first: np.ndarray, second: np.ndarray, *, bins: int = 60) -> DensityGrid:
    """Bin the central paired-value range and divide counts by value-space area."""
    if bins < 1:
        raise ValueError("The number of bins must be positive")
    first = np.asarray(first, dtype=np.float64).ravel()
    second = np.asarray(second, dtype=np.float64).ravel()
    if first.shape != second.shape:
        raise ValueError("Density inputs must have the same shape")
    valid = np.isfinite(first) & np.isfinite(second)
    first = first[valid]
    second = second[valid]
    if first.size == 0:
        raise ValueError("Density inputs have no paired finite values")
    x_edges = _density_edges(first, bins)
    y_edges = _density_edges(second, bins)
    inside = (
        (first >= x_edges[0])
        & (first <= x_edges[-1])
        & (second >= y_edges[0])
        & (second <= y_edges[-1])
    )
    counts, _, _ = np.histogram2d(first[inside], second[inside], bins=(x_edges, y_edges))
    area = np.multiply.outer(np.diff(x_edges), np.diff(y_edges))
    density = counts / area
    return DensityGrid(x_edges=x_edges, y_edges=y_edges, density=density, count=int(inside.sum()))


def interpolated_density(grid: DensityGrid, size: int = 256) -> np.ndarray:
    """Interpolate log density onto a regular value-positioned image grid."""
    if size < 2:
        raise ValueError("The interpolated density size must be at least two")
    x_centres = (grid.x_edges[:-1] + grid.x_edges[1:]) / 2
    y_centres = (grid.y_edges[:-1] + grid.y_edges[1:]) / 2
    values = np.pad(np.log1p(grid.density), 1, mode="edge")
    x_points = np.concatenate(([grid.x_edges[0]], x_centres, [grid.x_edges[-1]]))
    y_points = np.concatenate(([grid.y_edges[0]], y_centres, [grid.y_edges[-1]]))
    interpolator = RegularGridInterpolator(
        (x_points, y_points), values, bounds_error=False, fill_value=0.0
    )
    x = np.linspace(grid.x_edges[0], grid.x_edges[-1], size)
    y = np.linspace(grid.y_edges[0], grid.y_edges[-1], size)
    coordinates = np.stack(np.meshgrid(x, y, indexing="ij"), axis=-1)
    return interpolator(coordinates).T


def _pearson_pair(first: np.ndarray, second: np.ndarray) -> tuple[float, int]:
    """Return Pearson correlation after pairwise removal of non-finite observations."""
    first = np.asarray(first, dtype=np.float64).ravel()
    second = np.asarray(second, dtype=np.float64).ravel()
    if first.shape != second.shape:
        raise ValueError("Correlation inputs must have the same shape")
    valid = np.isfinite(first) & np.isfinite(second)
    count = int(valid.sum())
    if count < 2:
        return np.nan, count
    first = first[valid]
    second = second[valid]
    first = first - first.mean()
    second = second - second.mean()
    denominator = np.sqrt(np.dot(first, first) * np.dot(second, second))
    if denominator == 0:
        return np.nan, count
    return float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0)), count


def correlation_matrix(
    arrays: tuple[np.ndarray, ...], labels: tuple[str, ...], keys: tuple[str, ...]
) -> CorrelationMatrix:
    """Compute all Pearson correlations with pairwise finite-pixel removal."""
    if not (len(arrays) == len(labels) == len(keys)):
        raise ValueError("Arrays, labels and keys must have equal lengths")
    size = len(arrays)
    values = np.full((size, size), np.nan, dtype=np.float64)
    counts = np.zeros((size, size), dtype=np.int64)
    for row in range(size):
        for column in range(row, size):
            value, count = _pearson_pair(arrays[row], arrays[column])
            values[row, column] = values[column, row] = value
            counts[row, column] = counts[column, row] = count
    return CorrelationMatrix(labels=labels, keys=keys, values=values, counts=counts)


def sample_similarity_matrix(
    matrices: tuple[CorrelationMatrix, ...],
    labels: tuple[str, ...],
    sample_ids: tuple[str, ...],
) -> SampleSimilarityMatrix:
    """Correlate upper-triangle element-correlation fingerprints between samples."""
    if not (len(matrices) == len(labels) == len(sample_ids)):
        raise ValueError("Matrices, labels and sample IDs must have equal lengths")
    if not matrices:
        raise ValueError("At least one sample is required")
    keys = matrices[0].keys
    if any(matrix.keys != keys for matrix in matrices[1:]):
        raise ValueError("Sample fingerprints must use the same element keys")

    upper = np.triu_indices(len(keys), 1)
    fingerprints = np.asarray([matrix.values[upper] for matrix in matrices])
    feature_labels = tuple(
        f"{keys[row]} × {keys[column]}" for row, column in zip(*upper, strict=True)
    )
    size = len(matrices)
    values = np.full((size, size), np.nan, dtype=np.float64)
    counts = np.zeros((size, size), dtype=np.int64)
    for row in range(size):
        for column in range(row, size):
            value, count = _pearson_pair(fingerprints[row], fingerprints[column])
            values[row, column] = values[column, row] = value
            counts[row, column] = counts[column, row] = count
    return SampleSimilarityMatrix(
        labels=labels,
        sample_ids=sample_ids,
        values=values,
        counts=counts,
        feature_labels=feature_labels,
        fingerprints=fingerprints,
    )
