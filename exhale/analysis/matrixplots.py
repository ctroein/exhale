"""Renderer-independent descriptions of labelled matrix plots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..data.matrixpalettes import (
    ALL_MATRIX_PALETTES as ALL_MATRIX_PALETTES,
)
from ..data.matrixpalettes import (
    CORRELATION_COLOR_STOPS as CORRELATION_COLOR_STOPS,
)
from ..data.matrixpalettes import (
    MATRIX_PALETTES as MATRIX_PALETTES,
)
from ..data.matrixpalettes import (
    MATRIX_PALETTES_BY_KEY,
    ColorStop,
)
from ..data.matrixpalettes import (
    SEQUENTIAL_MATRIX_PALETTES as SEQUENTIAL_MATRIX_PALETTES,
)

NORMALIZED_DISTANCE_LABEL = "Observed / random placement"


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
            NORMALIZED_DISTANCE_LABEL if normalized else f"Mean nearest distance ({units})"
        ),
        show_values=show_values,
        decimals=decimals,
        secondary_values=standard_deviations,
        show_secondary=show_secondary,
        secondary_label="±",
    )
