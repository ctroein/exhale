"""Tests for directed distances between segmented element clusters."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from exhale.analysis.cluster_distances import (
    cluster_distance_matrix,
    normalize_cluster_distance_matrix,
)
from exhale.analysis.matrixplots import distance_matrix_spec, matrix_cell_text


def _channel(*points):
    return SimpleNamespace(
        cluster_df=pd.DataFrame(points, columns=("centroid-0", "centroid-1")),
        cluster_labels=None,
    )


def test_cluster_distances_are_directed_and_use_physical_resolution():
    first = _channel((0, 0), (10, 0))
    second = _channel((0, 1))

    result = cluster_distance_matrix(
        (first, second), ("A", "B"), ("a", "b"), resolution=2.0, units="µm"
    )

    np.testing.assert_allclose(result.values[0, 1], (1 + np.sqrt(101)) / 2 * 2)
    np.testing.assert_allclose(result.values[1, 0], 2.0)
    np.testing.assert_allclose(result.values[0, 0], 20.0)
    assert np.isnan(result.values[1, 1])
    np.testing.assert_allclose(result.standard_deviations[0, 0], 0.0)
    np.testing.assert_allclose(result.variances[0, 1], np.var((2.0, np.sqrt(101) * 2), ddof=1))
    np.testing.assert_allclose(
        result.standard_deviations[0, 1], np.std((2.0, np.sqrt(101) * 2), ddof=1)
    )
    assert np.isnan(result.standard_deviations[1, 0])
    np.testing.assert_array_equal(result.counts, (2, 1))


def test_cluster_distances_leave_empty_pairs_unavailable():
    result = cluster_distance_matrix(
        (_channel(), _channel((1, 2))),
        ("Empty", "B"),
        ("empty", "b"),
        resolution=1.0,
        units="px",
    )

    assert np.isnan(result.values).all()


def test_distance_matrix_spec_uses_finite_data_range_and_units():
    values = np.asarray(((np.nan, 3.0), (5.0, np.nan)))
    deviations = np.asarray(((np.nan, 1.0), (2.0, np.nan)))
    spec = distance_matrix_spec(
        values,
        ("A", "B"),
        units="µm",
        palette="viridis",
        standard_deviations=deviations,
        show_secondary=True,
    )

    assert spec.levels == (3.0, 5.0)
    assert spec.color_bar_label == "Mean nearest distance (µm)"
    assert spec.secondary_values is deviations
    assert spec.show_secondary
    assert matrix_cell_text(spec, 0, 1) == "3.00\n±1.00"

    normalized = distance_matrix_spec(values, ("A", "B"), units="µm", normalized=True)
    assert normalized.color_bar_label == "Observed / random placement"


def test_cluster_distances_normalize_to_reproducible_random_placement():
    first = _channel((1, 1), (5, 5))
    second = _channel((1, 5), (5, 1), (3, 3))
    first.cluster_labels = np.zeros((7, 7), dtype=np.int32)
    second.cluster_labels = np.zeros((7, 7), dtype=np.int32)
    first.cluster_labels[1, 1] = 1
    first.cluster_labels[5, 5] = 2
    second.cluster_labels[1, 5] = 1
    second.cluster_labels[5, 1] = 2
    second.cluster_labels[3, 3] = 3
    matrix = cluster_distance_matrix(
        (first, second), ("A", "B"), ("a", "b"), resolution=2.0, units="µm"
    )

    normalized = normalize_cluster_distance_matrix(
        matrix,
        (first, second),
        resolution=2.0,
        simulations=100,
        seed=4,
    )
    repeated = normalize_cluster_distance_matrix(
        matrix,
        (first, second),
        resolution=2.0,
        simulations=100,
        seed=4,
    )

    assert normalized.normalized
    assert normalized.units == ""
    assert normalized.random_expectations is not None
    np.testing.assert_allclose(
        normalized.values,
        matrix.values / normalized.random_expectations,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        normalized.standard_deviations,
        matrix.standard_deviations / normalized.random_expectations,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        normalized.random_expectations,
        repeated.random_expectations,
        equal_nan=True,
    )
