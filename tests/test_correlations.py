"""Tests for correlation calculations independent of the Qt interface."""

import numpy as np

from exhale.analysis.correlations import (
    DensityGrid,
    correlation_matrix,
    density_grid,
    interpolated_density,
    sample_similarity_matrix,
)
from exhale.analysis.matrixplots import (
    ALL_MATRIX_PALETTES,
    CORRELATION_COLOR_STOPS,
    MATRIX_PALETTES,
    correlation_matrix_spec,
    distance_matrix_spec,
    format_matrix_tick,
    matrix_color_bar_ticks,
    matrix_text_layout,
    use_dark_text,
)
from exhale.data.plotsettings import MATRIX_PALETTE_KEYS


def test_correlation_matrix_plot_spec_preserves_data_and_presentation():
    values = np.asarray(((1.0, -0.25), (-0.25, 1.0)))

    spec = correlation_matrix_spec(
        values,
        ("First", "Second"),
        show_values=False,
        decimals=4,
    )

    assert spec.values is values
    assert spec.labels == ("First", "Second")
    assert spec.levels == (-1.0, 1.0)
    assert spec.color_stops == CORRELATION_COLOR_STOPS
    assert spec.color_bar_label == "Pearson r"
    assert not spec.show_values
    assert spec.decimals == 4


def test_selectable_matrix_palettes_match_persisted_palette_keys():
    assert tuple(palette.key for palette in ALL_MATRIX_PALETTES) == MATRIX_PALETTE_KEYS
    assert tuple(palette.name for palette in MATRIX_PALETTES) == (
        "Magnolia",
        "Linnaea",
        "Utrumque",
        "Uarda",
        "Peccatorum",
        "Nightlife",
    )


def test_matrix_text_layout_derives_shared_cell_and_colorbar_spacing():
    spec = correlation_matrix_spec(
        np.eye(2),
        ("Cu", "Manganese"),
        show_values=True,
        decimals=2,
    )
    measured = matrix_text_layout(spec, 12.0, lambda text: len(text) * 6.0)

    assert measured.longest_label == 54.0
    assert measured.value_width == 24.0
    assert measured.minimum_cell == 24.0
    assert measured.default_cell == 30.0
    assert measured.preferred_cell == 36.0
    assert measured.page_padding == 12.0
    assert measured.row_label_width == 60.0
    assert measured.color_bar_label_gap == 7.0
    assert measured.color_bar_side_width == 65.2


def test_matrix_scale_ticks_do_not_exceed_cell_precision():
    assert format_matrix_tick(12.345, 2) == "12.35"
    assert format_matrix_tick(12.0, 2) == "12"
    assert format_matrix_tick(120.0, 0) == "120"


def test_matrix_color_bar_ticks_are_shared_and_evenly_spaced():
    ticks = matrix_color_bar_ticks((-1.0, 1.0), 2)

    assert len(ticks) == 21
    assert [tick for tick in ticks if tick[2]] == [
        (-1.0, "-1", True),
        (0.0, "0", True),
        (1.0, "1", True),
    ]


def test_matrix_text_layout_uses_largest_value_and_optional_second_line():
    spec = distance_matrix_spec(
        np.asarray(((1.0, 12345.0), (2.0, 3.0))),
        ("A", "B"),
        units="µm",
        standard_deviations=np.asarray(((0.5, 987.0), (1.0, 2.0))),
        show_secondary=True,
        decimals=0,
    )

    measured = matrix_text_layout(spec, 12.0, lambda text: len(text) * 6.0)

    assert measured.value_width == 30.0  # "12345", wider than "±987"
    assert measured.minimum_cell >= 2 * measured.font_height


def test_matrix_text_layout_fallback_respects_decimal_count():
    widths = []
    for decimals in range(4):
        spec = distance_matrix_spec(
            np.full((2, 2), np.nan),
            ("A", "B"),
            units="µm",
            decimals=decimals,
        )
        widths.append(matrix_text_layout(spec, 12.0, lambda text: len(text) * 6.0).value_width)

    assert widths == [6.0, 18.0, 24.0, 30.0]


def test_matrix_text_contrast_uses_perceived_brightness():
    assert use_dark_text(180, 220, 45)  # bright Viridis yellow-green
    assert use_dark_text(220, 200, 70)  # Cividis yellow
    assert not use_dark_text(33, 145, 140)  # mid-range Viridis teal


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


def test_interpolated_density_does_not_miss_bins_finer_than_display_grid():
    edges = np.linspace(0.0, 1.0, 1001)
    density = np.zeros((1000, 1000))
    density[500, 500] = 1.0
    grid = DensityGrid(edges, edges, density, count=1)

    image = interpolated_density(grid, size=256)

    assert image.max() > 0


def test_default_density_image_preserves_fine_grid_resolution():
    values = np.linspace(0.0, 1.0, 1000)
    grid = density_grid(values, values, bins=300)

    image = interpolated_density(grid)

    assert image.shape == (300, 300)


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
