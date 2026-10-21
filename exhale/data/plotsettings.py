"""Project-owned presentation settings for reusable matrix plots."""

from __future__ import annotations

from dataclasses import dataclass

ELEMENT_CORRELATIONS = "element_correlations"
SAMPLE_SIMILARITIES = "sample_similarities"
MATRIX_PLOT_KEYS = (ELEMENT_CORRELATIONS, SAMPLE_SIMILARITIES)
MATRIX_PALETTE_KEYS = (
    "blue-white-red",
    "purple-white-green",
    "brown-white-blue-green",
    "blue-black-red",
)


@dataclass
class MatrixPlotSettings:
    """Store the project-specific choices for one kind of matrix plot."""

    palette: str = "blue-white-red"
    show_values: bool = True
    decimals: int = 2
    color_bar_position: str = "right"

    def to_json(self) -> dict:
        return {
            "palette": self.palette,
            "show_values": self.show_values,
            "decimals": self.decimals,
            "color_bar_position": self.color_bar_position,
        }

    def apply_json(self, state: dict) -> None:
        palette = state.get("palette", self.palette)
        show_values = state.get("show_values", self.show_values)
        decimals = state.get("decimals", self.decimals)
        color_bar_position = state.get("color_bar_position", self.color_bar_position)
        if not isinstance(palette, str):
            raise TypeError("Matrix palette must be a string")
        if palette not in MATRIX_PALETTE_KEYS:
            raise ValueError("Unknown matrix palette")
        if not isinstance(show_values, bool):
            raise TypeError("Matrix value visibility must be true or false")
        if not isinstance(decimals, int) or not 1 <= decimals <= 4:
            raise ValueError("Matrix decimal count must be between 1 and 4")
        if color_bar_position not in ("left", "right", "hidden"):
            raise ValueError("Unknown matrix color-bar position")
        self.palette = palette
        self.show_values = show_values
        self.decimals = decimals
        self.color_bar_position = color_bar_position

    def reset(self) -> None:
        self.palette = "blue-white-red"
        self.show_values = True
        self.decimals = 2
        self.color_bar_position = "right"
