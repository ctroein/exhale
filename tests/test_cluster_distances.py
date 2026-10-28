"""Tests for directed distances between segmented element clusters."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from exhale.analysis.cluster_distances import (
    cluster_distance_matrix,
    random_placement_statistics,
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


def test_random_placement_uses_unexpanded_union_mask():
    first_mask = np.zeros((1, 5), dtype=np.int32)
    second_mask = np.zeros_like(first_mask)
    first_mask[0, 0] = 1
    second_mask[0, 4] = 1

    result = random_placement_statistics(
        (2,),
        (first_mask, second_mask),
        simulations=40,
        seed=2,
    )

    # Both support pixels must be selected. Jitter can alter their separation
    # by less than one pixel along the row.
    assert 3.0 < result.means[0, 0] < 5.0


def test_random_placement_simulates_complete_directed_matrix():
    mask = np.ones((8, 8), dtype=np.int32)

    result = random_placement_statistics(
        (1, 4),
        (mask, mask),
        simulations=300,
        seed=7,
    )

    assert np.isnan(result.means[0, 0])
    assert np.isnan(result.standard_deviations[0, 0])
    assert np.isfinite(result.means[1, 1])
    assert np.isfinite(result.standard_deviations[1, 1])
    assert result.means[0, 1] < result.means[1, 0]
    np.testing.assert_array_equal(result.counts, (1, 4))
    assert result.simulations == 300


def test_random_placement_is_reproducible():
    mask = np.ones((5, 6), dtype=np.int32)

    first = random_placement_statistics((2, 3), (mask, mask), simulations=50, seed=11)
    second = random_placement_statistics((2, 3), (mask, mask), simulations=50, seed=11)

    np.testing.assert_allclose(first.means, second.means, equal_nan=True)
    np.testing.assert_allclose(first.variances, second.variances, equal_nan=True)
    np.testing.assert_allclose(
        first.standard_deviations,
        second.standard_deviations,
        equal_nan=True,
    )


def test_random_placement_rejects_invalid_support_and_counts():
    mask = np.ones((2, 2), dtype=np.int32)

    with np.testing.assert_raises_regex(ValueError, "non-negative integers"):
        random_placement_statistics((1.5,), (mask,), simulations=2)
    with np.testing.assert_raises_regex(ValueError, "fewer pixels"):
        random_placement_statistics((5,), (mask,), simulations=2)
    with np.testing.assert_raises_regex(ValueError, "equal dimensions"):
        random_placement_statistics((1,), (mask, np.ones((3, 3))), simulations=2)


def test_null_percentiles_count_strictly_lower_simulated_means(monkeypatch):
    from exhale.analysis import cluster_distances as module

    draws = iter(np.array(((value, value), (np.nan, value))) for value in (1.0, 2.0, 3.0, 4.0))
    monkeypatch.setattr(module, "_random_distance_matrix", lambda _: next(draws))
    result = random_placement_statistics(
        (2, 2),
        (np.ones((3, 3)),),
        simulations=4,
        observed=np.array(((1.0, 5.0), (2.5, 3.0))),
    )
    np.testing.assert_allclose(result.percentiles, ((0.0, 100.0), (np.nan, 50.0)), equal_nan=True)


def test_null_percentiles_preserve_missing_observations_and_validate_shape():
    mask = np.ones((5, 5))
    result = random_placement_statistics(
        (1, 2), (mask,), simulations=20, observed=np.array(((np.nan, 0.0), (np.inf, np.nan)))
    )
    assert result.percentiles[0, 1] == 0.0
    assert np.isnan(result.percentiles[0, 0])
    assert np.isnan(result.percentiles[1]).all()
    with np.testing.assert_raises_regex(ValueError, "Observed distances must match"):
        random_placement_statistics((1, 2), (mask,), observed=np.ones((3, 3)))
