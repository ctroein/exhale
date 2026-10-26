"""Renderer-independent descriptions of labelled matrix plots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

Color = tuple[int, int, int, int]


@dataclass(frozen=True)
class ColorStop:
    """Associate one normalized position with an RGBA colour."""

    position: float
    color: Color


@dataclass(frozen=True)
class MatrixPlotSpec:
    """Describe matrix data and presentation independently of its renderer."""

    values: np.ndarray
    labels: tuple[str, ...]
    levels: tuple[float, float]
    color_stops: tuple[ColorStop, ...]
    color_bar_label: str
    show_values: bool = True
    decimals: int = 2
    secondary_values: np.ndarray | None = None
    show_secondary: bool = False
    secondary_label: str = ""


@dataclass(frozen=True)
class MatrixPalette:
    """Name one selectable matrix colour scale."""

    key: str
    name: str
    color_stops: tuple[ColorStop, ...]


@dataclass(frozen=True)
class MatrixTextLayout:
    """Measured text and spacing shared by interactive and export renderers."""

    font_height: float
    digit_width: float
    longest_label: float
    value_width: float
    minimum_cell: float
    default_cell: float
    preferred_cell: float
    page_padding: float
    row_label_width: float
    column_label_height: float
    column_label_gap: float
    color_bar_matrix_gap: float
    color_bar_width: float
    color_bar_tick_gap: float
    color_bar_tick_width: float
    color_bar_label_gap: float
    color_bar_label_width: float
    color_bar_min_height: float

    @property
    def color_bar_label_offset(self) -> float:
        """Return the distance from the bar edge to the title's near edge."""
        return self.color_bar_tick_gap + self.color_bar_tick_width + self.color_bar_label_gap

    @property
    def color_bar_side_width(self) -> float:
        """Return all horizontal space occupied by a visible colorbar."""
        return (
            self.color_bar_matrix_gap
            + self.color_bar_width
            + max(
                self.color_bar_tick_gap + self.color_bar_tick_width,
                self.color_bar_label_offset + self.color_bar_label_width,
            )
        )


MATRIX_PALETTES = (
    MatrixPalette(
        "magnolia",
        "Magnolia",
        (
            ColorStop(0.0, (49, 115, 149, 255)),
            ColorStop(0.225, (164, 196, 207, 255)),
            ColorStop(0.325, (185, 211, 220, 255)),
            ColorStop(0.5, (255, 255, 255, 255)),
            ColorStop(0.675, (233, 196, 199, 255)),
            ColorStop(0.775, (219, 173, 177, 255)),
            ColorStop(1.0, (165, 0, 0, 255)),
        ),
    ),
    MatrixPalette(
        "linnaea",
        "Linnaea",
        (
            ColorStop(0.0, (170, 61, 141, 255)),
            ColorStop(0.5, (247, 247, 247, 255)),
            ColorStop(1.0, (61, 122, 41, 255)),
        ),
    ),
    MatrixPalette(
        "utrumque",
        "Utrumque",
        (
            ColorStop(0.0, (156, 97, 20, 255)),
            ColorStop(0.5, (255, 255, 255, 255)),
            ColorStop(1.0, (0, 0, 128, 255)),
        ),
    ),
    MatrixPalette(
        "uarda",
        "Uarda",
        (
            ColorStop(0.0, (156, 97, 20, 255)),
            ColorStop(0.375, (78, 49, 10, 255)),
            ColorStop(0.5, (0, 0, 0, 255)),
            ColorStop(0.625, (0, 0, 64, 255)),
            ColorStop(1.0, (0, 0, 128, 255)),
        ),
    ),
    MatrixPalette(
        "peccatorum",
        "Peccatorum",
        (
            ColorStop(0.0, (185, 211, 220, 255)),
            ColorStop(0.1, (164, 196, 207, 255)),
            ColorStop(0.5, (32, 32, 32, 255)),
            ColorStop(0.9, (219, 173, 177, 255)),
            ColorStop(1.0, (233, 196, 199, 255)),
        ),
    ),
    MatrixPalette(
        "nightlife",
        "Nightlife",
        (
            ColorStop(0.0, (49, 54, 149, 255)),
            ColorStop(0.375, (25, 27, 75, 255)),
            ColorStop(0.5, (0, 0, 0, 255)),
            ColorStop(0.625, (83, 0, 19, 255)),
            ColorStop(1.0, (165, 0, 38, 255)),
        ),
    ),
)
SEQUENTIAL_MATRIX_PALETTES = (
    MatrixPalette(
        "viridis",
        "Viridis",
        (
            ColorStop(0.0, (68, 1, 84, 255)),
            ColorStop(0.25, (59, 82, 139, 255)),
            ColorStop(0.5, (33, 145, 140, 255)),
            ColorStop(0.75, (94, 201, 98, 255)),
            ColorStop(1.0, (253, 231, 37, 255)),
        ),
    ),
    MatrixPalette(
        "cividis",
        "Cividis",
        (
            ColorStop(0.0, (0, 32, 77, 255)),
            ColorStop(0.25, (66, 78, 108, 255)),
            ColorStop(0.5, (124, 124, 120, 255)),
            ColorStop(0.75, (188, 175, 109, 255)),
            ColorStop(1.0, (255, 233, 69, 255)),
        ),
    ),
    MatrixPalette(
        "magma",
        "Magma",
        (
            ColorStop(0.0, (0, 0, 4, 255)),
            ColorStop(0.25, (81, 18, 124, 255)),
            ColorStop(0.5, (183, 55, 121, 255)),
            ColorStop(0.75, (252, 137, 97, 255)),
            ColorStop(1.0, (252, 253, 191, 255)),
        ),
    ),
    MatrixPalette(
        "lundagård",
        "Lundagård",
        (
            ColorStop(0.0, (243, 241, 234, 255)),
            ColorStop(1 / 3, (203, 197, 169, 255)),
            ColorStop(2 / 3, (159, 196, 173, 255)),
            ColorStop(1.0, (155, 187, 198, 255)),
        ),
    ),
)
ALL_MATRIX_PALETTES = MATRIX_PALETTES + SEQUENTIAL_MATRIX_PALETTES
MATRIX_PALETTES_BY_KEY = {palette.key: palette for palette in ALL_MATRIX_PALETTES}
CORRELATION_COLOR_STOPS = MATRIX_PALETTES_BY_KEY["magnolia"].color_stops


def matrix_cell_text(spec: MatrixPlotSpec, row: int, column: int) -> str:
    """Format the primary and optional secondary value for one matrix cell."""
    return "\n".join(matrix_cell_lines(spec, row, column))


def matrix_cell_lines(spec: MatrixPlotSpec, row: int, column: int) -> tuple[str, ...]:
    """Format the aligned lines shown in one matrix cell."""
    value = spec.values[row, column]
    if not np.isfinite(value):
        return ()
    lines = [f"{value:.{spec.decimals}f}"]
    if spec.show_secondary and spec.secondary_values is not None:
        secondary = spec.secondary_values[row, column]
        if np.isfinite(secondary):
            lines.append(f"{spec.secondary_label}{secondary:.{spec.decimals}f}")
    return tuple(lines)


def use_dark_text(red: int, green: int, blue: int) -> bool:
    """Return whether black text has better practical contrast on an RGB fill."""
    channels = np.asarray((red, green, blue), dtype=np.float64) / 255.0
    linear = np.where(
        channels <= 0.04045,
        channels / 12.92,
        ((channels + 0.055) / 1.055) ** 2.4,
    )
    luminance = float(np.dot(linear, (0.2126, 0.7152, 0.0722)))
    return luminance >= 0.42


def format_matrix_tick(value: float, decimals: int) -> str:
    """Format a scale value with no more precision than the matrix cells."""
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if decimals else text


def matrix_color_bar_ticks(
    levels: tuple[float, float], decimals: int
) -> tuple[tuple[float, str, bool], ...]:
    """Return the shared major and minor ticks for matrix color scales."""
    lower, upper = levels
    ticks = []
    for index in range(21):
        position = index / 20
        value = lower + position * (upper - lower)
        major = index in (0, 10, 20)
        ticks.append((value, format_matrix_tick(value, decimals) if major else "", major))
    return tuple(ticks)


def matrix_text_layout(
    spec: MatrixPlotSpec,
    font_height: float,
    measure_text: Callable[[str], float],
    em_size: float | None = None,
) -> MatrixTextLayout:
    """Measure renderer-independent matrix text and derive standard spacing."""
    if em_size is None:
        em_size = font_height
    digit_width = measure_text("0")
    longest_label = max((measure_text(label) for label in spec.labels), default=0.0)
    formatted = [
        f"{value:.{spec.decimals}f}" for value in spec.values.ravel() if np.isfinite(value)
    ]
    if spec.show_secondary and spec.secondary_values is not None:
        formatted.extend(
            f"{spec.secondary_label}{value:.{spec.decimals}f}"
            for value in spec.secondary_values.ravel()
            if np.isfinite(value)
        )
    value_width = max(
        (measure_text(value) for value in formatted),
        default=measure_text(f"{0:.{spec.decimals}f}"),
    )
    if spec.show_values:
        lines = 2 if spec.show_secondary and spec.secondary_values is not None else 1
        text_height = lines * font_height
        minimum_cell = max(value_width, text_height + 2.0)
        default_cell = max(text_height + 2.0, value_width + digit_width)
        preferred_cell = max(text_height + 2.0, value_width + digit_width * 2.0)
    else:
        minimum_cell = font_height
        default_cell = font_height * 2.0
        preferred_cell = font_height * 2.0
    return MatrixTextLayout(
        font_height=font_height,
        digit_width=digit_width,
        longest_label=longest_label,
        value_width=value_width,
        minimum_cell=minimum_cell,
        default_cell=default_cell,
        preferred_cell=preferred_cell,
        page_padding=em_size,
        row_label_width=longest_label + font_height * 0.5,
        column_label_height=(longest_label + font_height) / np.sqrt(2.0) + font_height * 0.3,
        column_label_gap=font_height * 0.3,
        color_bar_matrix_gap=font_height * 1.5,
        color_bar_width=font_height * 0.6,
        color_bar_tick_gap=digit_width * 1.5,
        color_bar_tick_width=max(
            measure_text(format_matrix_tick(spec.levels[0], spec.decimals)),
            measure_text(format_matrix_tick(spec.levels[1], spec.decimals)),
        ),
        color_bar_label_gap=font_height - digit_width * 5.0 / 6.0,
        color_bar_label_width=font_height,
        color_bar_min_height=measure_text(spec.color_bar_label) + font_height,
    )


def correlation_matrix_spec(
    values: np.ndarray,
    labels: tuple[str, ...],
    *,
    palette: str = "magnolia",
    show_values: bool = True,
    decimals: int = 2,
) -> MatrixPlotSpec:
    """Describe a Pearson-correlation matrix using the current default style."""
    return MatrixPlotSpec(
        values=values,
        labels=labels,
        levels=(-1.0, 1.0),
        color_stops=MATRIX_PALETTES_BY_KEY[palette].color_stops,
        color_bar_label="Pearson r",
        show_values=show_values,
        decimals=decimals,
    )


def distance_matrix_spec(
    values: np.ndarray,
    labels: tuple[str, ...],
    *,
    units: str,
    standard_deviations: np.ndarray | None = None,
    palette: str = "viridis",
    show_values: bool = True,
    decimals: int = 2,
    show_secondary: bool = False,
    normalized: bool = False,
) -> MatrixPlotSpec:
    """Describe a non-negative directed-distance matrix."""
    finite = values[np.isfinite(values)]
    lower = float(finite.min()) if finite.size else 0.0
    upper = float(finite.max()) if finite.size else 1.0
    if lower == upper:
        lower, upper = (0.0, upper) if upper > 0 else (0.0, 1.0)
    return MatrixPlotSpec(
        values=values,
        labels=labels,
        levels=(lower, upper),
        color_stops=MATRIX_PALETTES_BY_KEY[palette].color_stops,
        color_bar_label=(
            "Observed / random placement" if normalized else f"Mean nearest distance ({units})"
        ),
        show_values=show_values,
        decimals=decimals,
        secondary_values=standard_deviations,
        show_secondary=show_secondary,
        secondary_label="±",
    )
