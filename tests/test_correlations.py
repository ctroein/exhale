"""Tests for correlation calculations independent of the Qt interface."""

import numpy as np

from exhale.analysis.correlations import (
    correlation_matrix,
    density_grid,
    interpolated_density,
    sample_similarity_matrix,
)


def test_density_grid_uses_regular_value_coordinates_and_bin_areas():
    first = np.linspace(0.0, 10.0, 101)
    second = first * 2

    grid = density_grid(first, second, bins=2)

    np.testing.assert_allclose(np.diff(grid.x_edges), np.diff(grid.x_edges)[0])
    np.testing.assert_allclose(np.diff(grid.y_edges), np.diff(grid.y_edges)[0])
    expected_area = np.multiply.outer(np.diff(grid.x_edges), np.diff(grid.y_edges))
    recovered_counts = grid.density * expected_area
    assert recovered_counts[0, 1] == recovered_counts[1, 0] == 0
    assert recovered_counts.sum() == grid.count
    assert grid.count == 101


def test_density_grid_filters_nonfinite_pairs_and_handles_constant_data():
    grid = density_grid(
        np.asarray([3.0, 3.0, np.nan, 3.0]),
        np.asarray([5.0, 5.0, 8.0, np.inf]),
    )

    assert grid.count == 2
    assert grid.density.shape == (1, 1)
    assert np.isfinite(grid.density[0, 0])


def test_interpolated_density_preserves_requested_shape_and_range():
    grid = density_grid(
        np.asarray([0.0, 1.0, 2.0, 10.0]),
        np.asarray([0.0, 2.0, 4.0, 20.0]),
        bins=2,
    )

    image = interpolated_density(grid, size=17)

    assert image.shape == (17, 17)
    assert np.isfinite(image).all()
    assert image.min() >= 0
    assert image.max() > image.min()


def test_element_correlations_remove_nonfinite_pixels_pairwise():
    arrays = (
        np.array([[1.0, 2.0], [3.0, np.nan]]),
        np.array([[2.0, 4.0], [6.0, 100.0]]),
        np.array([[3.0, 2.0], [1.0, 0.0]]),
    )

    result = correlation_matrix(arrays, ("A", "B", "C"), ("a", "b", "c"))

    np.testing.assert_allclose(result.values[0], (1.0, 1.0, -1.0))
    assert result.counts[0, 1] == 3
    assert result.counts[1, 2] == 4
    np.testing.assert_array_equal(result.values, result.values.T)


def test_constant_input_produces_nan():
    result = correlation_matrix(
        (np.ones((2, 2)), np.arange(4).reshape(2, 2)), ("A", "B"), ("a", "b")
    )

    assert np.isnan(result.values[0, 0])
    assert np.isnan(result.values[0, 1])
    assert result.counts[0, 1] == 4


def test_sample_similarities_use_aligned_upper_triangles():
    base = np.array(
        [
            [1.0, 0.1, 0.2, 0.3],
            [0.1, 1.0, 0.4, 0.5],
            [0.2, 0.4, 1.0, 0.6],
            [0.3, 0.5, 0.6, 1.0],
        ]
    )
    inverse = base.copy()
    inverse[np.triu_indices(4, 1)] = base[np.triu_indices(4, 1)][::-1]
    inverse = np.triu(inverse) + np.triu(inverse, 1).T
    matrices = tuple(
        correlation_matrix(
            tuple(np.arange(8, dtype=float).reshape(2, 4) for _ in range(4)),
            ("A", "B", "C", "D"),
            ("a", "b", "c", "d"),
        )
        for _ in range(2)
    )
    matrices = (
        matrices[0].__class__(matrices[0].labels, matrices[0].keys, base, matrices[0].counts),
        matrices[1].__class__(matrices[1].labels, matrices[1].keys, inverse, matrices[1].counts),
    )

    result = sample_similarity_matrix(matrices, ("First", "Second"), ("1", "2"))

    assert result.feature_labels == ("a × b", "a × c", "a × d", "b × c", "b × d", "c × d")
    np.testing.assert_allclose(result.values, ((1.0, -1.0), (-1.0, 1.0)))
    np.testing.assert_array_equal(result.counts, ((6, 6), (6, 6)))
