"""Canonical palette definitions for project matrix plots."""

from __future__ import annotations

from dataclasses import dataclass

Color = tuple[int, int, int, int]


@dataclass(frozen=True)
class ColorStop:
    """Associate one normalized position with an RGBA colour."""

    position: float
    color: Color


@dataclass(frozen=True)
class MatrixPalette:
    """Name one selectable matrix colour scale."""

    key: str
    name: str
    color_stops: tuple[ColorStop, ...]


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


MATRIX_PALETTE_KEYS = tuple(palette.key for palette in ALL_MATRIX_PALETTES)
