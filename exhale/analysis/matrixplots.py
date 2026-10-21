"""Renderer-independent descriptions of labelled matrix plots."""

from __future__ import annotations

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


MATRIX_PALETTES = (
    MatrixPalette(
        "blue-white-red",
        "Blue – white – red",
        (
            ColorStop(0.0, (49, 54, 149, 255)),
            ColorStop(0.5, (255, 255, 255, 255)),
            ColorStop(1.0, (165, 0, 38, 255)),
        ),
    ),
    MatrixPalette(
        "purple-white-green",
        "Purple – white – green",
        (
            ColorStop(0.0, (118, 42, 131, 255)),
            ColorStop(0.5, (247, 247, 247, 255)),
            ColorStop(1.0, (0, 136, 55, 255)),
        ),
    ),
    MatrixPalette(
        "brown-white-blue-green",
        "Brown – white – teal",
        (
            ColorStop(0.0, (140, 81, 10, 255)),
            ColorStop(0.5, (245, 245, 245, 255)),
            ColorStop(1.0, (1, 102, 94, 255)),
        ),
    ),
    MatrixPalette(
        "blue-black-red",
        "Blue – black – red",
        (
            ColorStop(0.0, (49, 54, 149, 255)),
            ColorStop(0.5, (0, 0, 0, 255)),
            ColorStop(1.0, (165, 0, 38, 255)),
        ),
    ),
)
MATRIX_PALETTES_BY_KEY = {palette.key: palette for palette in MATRIX_PALETTES}
CORRELATION_COLOR_STOPS = MATRIX_PALETTES_BY_KEY["blue-white-red"].color_stops


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
