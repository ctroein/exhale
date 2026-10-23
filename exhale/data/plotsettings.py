"""Project-owned presentation settings for reusable matrix plots."""

from __future__ import annotations

from dataclasses import dataclass, field

ELEMENT_CORRELATIONS = "element_correlations"
SAMPLE_SIMILARITIES = "sample_similarities"
CLUSTER_DISTANCES = "cluster_distances"
MATRIX_PLOT_KEYS = (ELEMENT_CORRELATIONS, SAMPLE_SIMILARITIES, CLUSTER_DISTANCES)
MATRIX_PALETTE_KEYS = (
    "magnolia",
    "linnaea",
    "utrumque",
    "uarda",
    "peccatorum",
    "nightlife",
    "viridis",
    "cividis",
    "magma",
)


def _dimension_from_json(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Matrix {name} must be a number or null")
    value = float(value)
    if not 10.0 <= value <= 2000.0:
        raise ValueError(f"Matrix {name} must be between 10 and 2000 mm")
    return value


@dataclass
class MatrixPublicationSettings:
    """Store publication typography shared by all project matrix plots."""

    font_family: str = ""
    font_size: float = 10.0

    def to_json(self) -> dict:
        return {
            "font_family": self.font_family,
            "font_size": self.font_size,
        }

    def apply_json(self, state: dict) -> None:
        font_family = state.get("font_family", self.font_family)
        font_size = state.get("font_size", self.font_size)
        if not isinstance(font_family, str):
            raise TypeError("Matrix font family must be a string")
        if isinstance(font_size, bool) or not isinstance(font_size, (int, float)):
            raise TypeError("Matrix font size must be a number")
        font_size = float(font_size)
        if not 4.0 <= font_size <= 72.0:
            raise ValueError("Matrix font size must be between 4 and 72 pt")
        self.font_family = font_family
        self.font_size = font_size

    def reset(self) -> None:
        self.font_family = ""
        self.font_size = 10.0


@dataclass
class MatrixPlotSettings:
    """Store the project-specific choices for one kind of matrix plot."""

    palette: str = "magnolia"
    show_values: bool = True
    show_secondary: bool = False
    decimals: int = 2
    color_bar_position: str = "right"
    width_mm: float | None = None
    height_mm: float | None = None
    cell_borders: bool = False
    dpi: int = 300
    default_palette: str = field(default="magnolia", repr=False, compare=False)

    def to_json(self) -> dict:
        return {
            "palette": self.palette,
            "show_values": self.show_values,
            "show_secondary": self.show_secondary,
            "decimals": self.decimals,
            "color_bar_position": self.color_bar_position,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "cell_borders": self.cell_borders,
            "dpi": self.dpi,
        }

    def apply_json(self, state: dict) -> None:
        palette = state.get("palette", self.palette)
        show_values = state.get("show_values", self.show_values)
        show_secondary = state.get("show_secondary", self.show_secondary)
        decimals = state.get("decimals", self.decimals)
        color_bar_position = state.get("color_bar_position", self.color_bar_position)
        width_mm = _dimension_from_json(state.get("width_mm", self.width_mm), "width")
        height_mm = _dimension_from_json(state.get("height_mm", self.height_mm), "height")
        cell_borders = state.get("cell_borders", self.cell_borders)
        dpi = state.get("dpi", self.dpi)
        if not isinstance(palette, str):
            raise TypeError("Matrix palette must be a string")
        if palette not in MATRIX_PALETTE_KEYS:
            raise ValueError("Unknown matrix palette")
        if not isinstance(show_values, bool):
            raise TypeError("Matrix value visibility must be true or false")
        if not isinstance(show_secondary, bool):
            raise TypeError("Matrix secondary-value visibility must be true or false")
        if not isinstance(decimals, int) or not 0 <= decimals <= 6:
            raise ValueError("Matrix decimal count must be between 0 and 6")
        if color_bar_position not in ("left", "right", "hidden"):
            raise ValueError("Unknown matrix color-bar position")
        if not isinstance(cell_borders, bool):
            raise TypeError("Matrix cell borders must be a boolean")
        if isinstance(dpi, bool) or not isinstance(dpi, int):
            raise TypeError("Matrix DPI must be an integer")
        if not 72 <= dpi <= 2400:
            raise ValueError("Matrix DPI must be between 72 and 2400")
        self.palette = palette
        self.show_values = show_values
        self.show_secondary = show_secondary
        self.decimals = decimals
        self.color_bar_position = color_bar_position
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.cell_borders = cell_borders
        self.dpi = dpi

    def reset(self) -> None:
        self.palette = self.default_palette
        self.show_values = True
        self.show_secondary = False
        self.decimals = 2
        self.color_bar_position = "right"
        self.width_mm = None
        self.height_mm = None
        self.cell_borders = False
        self.dpi = 300
