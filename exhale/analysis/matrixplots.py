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

    @property
    def color_bar_label_offset(self) -> float:
        """Return the distance from the bar edge to the title's near edge."""
        return self.color_bar_tick_gap + self.digit_width + self.color_bar_label_gap

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
        "blue-white-red",
        "Blue–white–red",
        (
            ColorStop(0.0, (49, 54, 149, 255)),
            ColorStop(0.5, (255, 255, 255, 255)),
            ColorStop(1.0, (165, 0, 38, 255)),
        ),
    ),
    MatrixPalette(
        "purple-white-green",
        "Purple–white–green",
        (
            ColorStop(0.0, (118, 42, 131, 255)),
            ColorStop(0.5, (247, 247, 247, 255)),
            ColorStop(1.0, (0, 136, 55, 255)),
        ),
    ),
    MatrixPalette(
        "brown-white-blue-green",
        "Brown–white–teal",
        (
            ColorStop(0.0, (140, 81, 10, 255)),
            ColorStop(0.5, (245, 245, 245, 255)),
            ColorStop(1.0, (1, 102, 94, 255)),
        ),
    ),
    MatrixPalette(
        "blue-black-red",
        "Blue–black–red",
        (
            ColorStop(0.0, (49, 54, 149, 255)),
            ColorStop(0.5, (0, 0, 0, 255)),
            ColorStop(1.0, (165, 0, 38, 255)),
        ),
    ),
)
MATRIX_PALETTES_BY_KEY = {palette.key: palette for palette in MATRIX_PALETTES}
CORRELATION_COLOR_STOPS = MATRIX_PALETTES_BY_KEY["blue-white-red"].color_stops


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
    value_width = measure_text(f"-{0:.{spec.decimals}f}")
    if spec.show_values:
        minimum_cell = value_width + digit_width * 0.5
        preferred_cell = max(font_height + 2.0, value_width + digit_width * 2.0)
    else:
        minimum_cell = font_height
        preferred_cell = font_height * 2.0
    return MatrixTextLayout(
        font_height=font_height,
        digit_width=digit_width,
        longest_label=longest_label,
        value_width=value_width,
        minimum_cell=minimum_cell,
        preferred_cell=preferred_cell,
        page_padding=em_size * 2.0,
        row_label_width=longest_label + font_height * 0.5,
        column_label_height=(longest_label + font_height) / np.sqrt(2.0) + font_height * 0.3,
        column_label_gap=font_height * 0.3,
        color_bar_matrix_gap=font_height * 1.5,
        color_bar_width=font_height * 0.6,
        color_bar_tick_gap=digit_width * 1.5,
        color_bar_tick_width=measure_text("-1.00"),
        color_bar_label_gap=font_height - digit_width * 5.0 / 6.0,
        color_bar_label_width=font_height,
    )


def correlation_matrix_spec(
    values: np.ndarray,
    labels: tuple[str, ...],
    *,
    palette: str = "blue-white-red",
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
