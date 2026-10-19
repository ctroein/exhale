#!/usr/bin/env python3
"""Compose configured channel maps into exact RGBA publication images."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..data.constants import DISPLAY_UNITS
from ..data.imagesettings import ImageSettings, Layouts, Scalebars

Image.MAX_IMAGE_PIXELS = None

_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _rgb255(rgb, alpha=255):
    values = np.clip(np.asarray(rgb, dtype=float), 0, 1)
    channels = [int(round(255 * value)) for value in values[:3]]
    return tuple(channels + [int(alpha)])


def _array_to_rgba(array):
    array = np.clip(np.asarray(array, dtype=float), 0, 1)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    alpha = np.full(array.shape[:2] + (1,), 255, dtype=np.uint8)
    rgb = np.round(array[..., :3] * 255).astype(np.uint8)
    return np.concatenate([rgb, alpha], axis=2)


def _resize_rgba(array, size):
    image = Image.fromarray(_array_to_rgba(array), mode="RGBA")
    if image.size != tuple(size):
        image = image.resize(tuple(size), resample=Image.Resampling.NEAREST)
    return image


def _font(size):
    size = max(1, int(round(size)))
    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _outline_color(rgb):
    rgb = np.clip(np.asarray(rgb, dtype=float), 0, 1)
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    luma = float((linear * _LUMA).sum())
    if luma < 0.05:
        return _rgb255([1, 1, 1], alpha=153)
    if luma < 0.12:
        return _rgb255(rgb / 2, alpha=153)
    return _rgb255([0, 0, 0], alpha=153)


def _format_length(value, units):
    """Convert a physical length to a suitable display prefix."""
    if units not in DISPLAY_UNITS:
        return f"{value:g} {units}"
    value_nm = value * DISPLAY_UNITS[units]
    chosen_unit, chosen_scale = "nm", 1.0
    for unit, scale in DISPLAY_UNITS.items():
        if value_nm / scale >= 1:
            chosen_unit, chosen_scale = unit, scale
    return f"{value_nm / chosen_scale:g} {chosen_unit}"


def _nice_number(value):
    if value <= 0:
        return 0
    exponent = math.floor(math.log10(value))
    fraction = value / (10**exponent)
    if fraction < 1.5:
        nice_fraction = 1
    elif fraction < 3.5:
        nice_fraction = 2
    elif fraction < 7.5:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * (10**exponent)


def _nearest_lookup(source_size, target_size):
    """Return Pillow's exact nearest-neighbour source index for each output."""
    indices = np.arange(source_size, dtype=np.int32).reshape(1, source_size)
    resized = Image.fromarray(indices, mode="I").resize(
        (target_size, 1), resample=Image.Resampling.NEAREST
    )
    return np.asarray(resized, dtype=np.intp)[0].copy()


@dataclass(frozen=True)
class ComposedImageMapping:
    """Map pixels in the composed canvas back to the merged source map."""

    x: int
    y: int
    width: int
    height: int
    source_x: np.ndarray
    source_y: np.ndarray

    def map(self, x, y):
        """Map a continuous canvas position to a source ``(x, y)`` pixel."""
        canvas_x = math.floor(x)
        canvas_y = math.floor(y)
        local_x = canvas_x - self.x
        local_y = canvas_y - self.y
        if not (0 <= local_x < self.width and 0 <= local_y < self.height):
            return None
        return int(self.source_x[local_x]), int(self.source_y[local_y])


@dataclass(frozen=True)
class _LayoutGeometry:
    """Pixel geometry for the element strip and merged panel."""

    width: int
    height: int
    merged_x: int
    merged_y: int
    merged_width: int
    merged_height: int
    merged_scale: float
    element_x: tuple[int, ...]
    element_y: tuple[int, ...]


@dataclass(frozen=True)
class RasterPrimitive:
    """A native-resolution array placed in a composition rectangle."""

    array: np.ndarray
    rect: tuple[int, int, int, int]
    cache_key: object | None = None


@dataclass(frozen=True)
class ColoredRasterPrimitive:
    """A scalar array colourized and additively blended for interactive display."""

    array: np.ndarray
    rect: tuple[float, float, float, float]
    color: tuple[float, float, float]


@dataclass(frozen=True)
class RectanglePrimitive:
    """A filled or outlined rectangle in composition coordinates."""

    box: tuple[int, int, int, int]
    fill: tuple[int, int, int, int] | None = None
    outline: tuple[int, int, int, int] | None = None
    width: int = 1


@dataclass(frozen=True)
class TextPrimitive:
    """Anchored text in composition coordinates."""

    xy: tuple[int, int]
    text: str
    font_size: float
    fill: tuple[int, int, int, int]
    anchor: str
    font_family: str = "DejaVu Sans"
    outlined: bool = False


@dataclass(frozen=True)
class LinePrimitive:
    """A solid line in composition coordinates."""

    xy: tuple[tuple[int, int], tuple[int, int]]
    fill: tuple[int, int, int, int]
    width: int


@dataclass(frozen=True)
class CompositionDescription:
    """Renderer-independent content and geometry for one composition."""

    size: tuple[int, int]
    background: tuple[int, int, int, int]
    primitives: tuple[
        RasterPrimitive
        | ColoredRasterPrimitive
        | RectanglePrimitive
        | TextPrimitive
        | LinePrimitive,
        ...,
    ]
    mapping: ComposedImageMapping


class ImageComposer:
    """Merge, arrange, annotate, and optionally save configured element maps."""

    def __init__(self):
        self.coord_mapping = None
        self._layer_cache = {}
        self._strip_image_cache = {}

    @staticmethod
    def _element_layer_key(element):
        return (
            element,
            element.normalizer.value,
            tuple(element.trfRange),
            element.gamma,
            element.data.shape,
        )

    def _layers(self, elements):
        """Return transformed element maps, reusing color-independent work."""
        keys = {slot: self._element_layer_key(element) for slot, element in elements}
        layers = {}
        for slot, element in elements:
            key = keys[slot]
            layers[slot] = self._layer_cache.get(key)
            if layers[slot] is None:
                layers[slot] = element.transformedData()
        self._layer_cache = {keys[slot]: layer for slot, layer in layers.items()}
        self._strip_image_cache = {
            key: image for key, image in self._strip_image_cache.items() if key in self._layer_cache
        }
        return keys, layers

    @staticmethod
    def merged_image(image: ImageSettings, layers=None):
        "Merge the element images with different colors"
        # We don't cache the merged image because the colors etc could change
        # so easily anyway.
        elements = image.elements

        shapes = np.array([es.data.shape for es in elements.values()])
        shape = np.max(shapes, axis=0)
        merged = np.zeros(list(shape) + [3])
        colors = image.colorscheme.colors()
        maxcolor = colors[list(elements.keys())].sum(0)
        maxcolor[maxcolor <= 0] = 1
        # print("maxcolor", maxcolor)
        for i, es in elements.items():
            td = es.transformedData() if layers is None else layers[i]
            h, w = td.shape
            merged[:h, :w] = merged[:h, :w] + td[..., None] * colors[i]
        if image.clipColors:
            return np.minimum(merged, 1.0)
        return merged / maxcolor

    def display_composed_image(self, canvas, image: ImageSettings, *, reset_view=False):
        "Render a composed image into an ImageCanvas."
        if not image.elements:
            self.coord_mapping = None
            canvas.clear_image()
            return
        description = self.describe(image, additive=True)
        self.coord_mapping = description.mapping
        canvas.set_composition(description, reset_view=reset_view)

    def map_coordinates(self, x, y):
        "Map top-left-origin composed-canvas coordinates to source pixels."
        if self.coord_mapping is None:
            return None
        return self.coord_mapping.map(x, y)

    @staticmethod
    def get_format_filters():
        return [
            "PNG (*.png)",
            "PDF (*.pdf)",
            "TIFF (*.tif *.tiff)",
            "JPEG (*.jpg *.jpeg)",
            "All files (*)",
        ]

    @staticmethod
    def _layout_geometry(image, element_shapes, merged_shape):
        """Calculate all canvas and panel positions for one layout."""
        merged_height, merged_width = merged_shape
        border_width = int(image.borderWidth)
        element_count = len(element_shapes)

        if image.layout in (Layouts.IL, Layouts.IR):
            strip_width = int(element_shapes[:, 1].max())
            strip_height = int(element_shapes[:, 0].sum() + border_width * (element_count - 1))
            merged_scale = strip_height / merged_height
            output_merged_width = int(round(merged_width * merged_scale))
            output_merged_height = strip_height
            width = int(strip_width + output_merged_width + 3 * border_width)
            height = int(strip_height + 2 * border_width)

            element_x = [border_width] * element_count
            if image.layout == Layouts.IR:
                element_x = [
                    int(width - border_width - item_width)
                    for _item_height, item_width in element_shapes
                ]
            element_y = (
                np.cumsum(element_shapes[:, 0] + border_width) - element_shapes[0, 0]
            ).astype(int)
            merged_x = (
                2 * border_width + strip_width if image.layout == Layouts.IL else border_width
            )
            merged_y = border_width

        elif image.layout in (Layouts.IA, Layouts.IB):
            strip_width = int(element_shapes[:, 1].sum() + border_width * (element_count - 1))
            strip_height = int(element_shapes[:, 0].max())
            merged_scale = strip_width / merged_width
            output_merged_width = strip_width
            output_merged_height = int(round(merged_height * merged_scale))
            width = int(strip_width + 2 * border_width)
            height = int(strip_height + output_merged_height + 3 * border_width)

            element_y = [border_width] * element_count
            if image.layout == Layouts.IB:
                element_y = [
                    int(height - border_width - item_height)
                    for item_height, _item_width in element_shapes
                ]
            element_x = (
                np.cumsum(element_shapes[:, 1] + border_width) - element_shapes[0, 1]
            ).astype(int)
            merged_x = border_width
            merged_y = (
                2 * border_width + strip_height if image.layout == Layouts.IA else border_width
            )

        elif image.layout == Layouts.MERGED:
            merged_scale = 1.0
            output_merged_width = int(merged_width)
            output_merged_height = int(merged_height)
            width = int(merged_width + 2 * border_width)
            height = int(merged_height + 2 * border_width)
            element_x = ()
            element_y = ()
            merged_x = border_width
            merged_y = border_width

        else:
            raise NotImplementedError(image.layout)

        return _LayoutGeometry(
            width=width,
            height=height,
            merged_x=int(merged_x),
            merged_y=int(merged_y),
            merged_width=output_merged_width,
            merged_height=output_merged_height,
            merged_scale=merged_scale,
            element_x=tuple(int(value) for value in element_x),
            element_y=tuple(int(value) for value in element_y),
        )

    @staticmethod
    def _scale_bar_primitives(image, geometry, font_size):
        """Describe a physical scale bar when resolution and placement permit it."""
        if image.scalebar == Scalebars.NONE:
            return ()
        resolution, units = image.resolution
        if resolution is None or resolution <= 0 or units == "None":
            return ()

        target_length = (geometry.merged_width / geometry.merged_scale) * resolution * 0.20
        physical_length = _nice_number(target_length)
        if physical_length <= 0:
            return ()

        bar_width = int(round((physical_length / resolution) * geometry.merged_scale))
        bar_width = max(8, min(bar_width, int(0.8 * geometry.merged_width)))
        line_width = max(2, int(round(font_size * 0.18)))
        padding = max(4, int(round(font_size * 0.7)))
        text_gap = max(2, int(round(font_size * 0.25)))
        label = _format_length(physical_length, units)
        font = _font(font_size)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = measure.textbbox((0, 0), label, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        if image.scalebar in (Scalebars.LL, Scalebars.UL):
            x0 = geometry.merged_x + padding
        else:
            x0 = geometry.merged_x + geometry.merged_width - padding - bar_width
        if image.scalebar in (Scalebars.LL, Scalebars.LR):
            line_y = geometry.merged_y + geometry.merged_height - padding - text_height - text_gap
            text_y = line_y + text_gap
        else:
            text_y = geometry.merged_y + padding
            line_y = text_y + text_height + text_gap
        x1 = x0 + bar_width

        primitives = []
        if image.scalebarBgAlpha is not None:
            box_x0 = min(x0, x0 + (bar_width - text_width) // 2) - padding // 2
            box_x1 = max(x1, x0 + (bar_width + text_width) // 2) + padding // 2
            box_y0 = min(text_y, line_y) - padding // 2
            box_y1 = max(text_y + text_height, line_y + line_width) + padding // 2
            primitives.append(
                RectanglePrimitive(
                    (box_x0, box_y0, box_x1, box_y1),
                    fill=_rgb255(
                        image.scalebarBgColor,
                        alpha=int(round(255 * image.scalebarBgAlpha)),
                    ),
                )
            )

        color = _rgb255(image.scalebarColor)
        primitives.append(LinePrimitive(((x0, line_y), (x1, line_y)), fill=color, width=line_width))
        primitives.append(
            TextPrimitive(
                (x0 + bar_width // 2, text_y),
                label,
                font_size,
                color,
                "ma",
            )
        )
        return tuple(primitives)

    @staticmethod
    def _draw_outlined_text(canvas, primitive):
        """Draw an outlined text primitive onto a Pillow canvas."""
        font = _font(primitive.font_size)
        stroke_width = max(1, int(round(0.06 * font.size)))
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, mode="RGBA")
        outline = _outline_color(np.array(primitive.fill[:3]) / 255.0)
        x, y = primitive.xy
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx * dx + dy * dy <= stroke_width * stroke_width:
                    draw.text(
                        (x + dx, y + dy),
                        primitive.text,
                        font=font,
                        fill=outline,
                        anchor=primitive.anchor,
                    )
        draw.text(
            primitive.xy,
            primitive.text,
            font=font,
            fill=primitive.fill,
            anchor=primitive.anchor,
        )
        canvas.alpha_composite(overlay)

    def _render_description(self, description):
        """Render a composition description through the exact Pillow path."""
        canvas = Image.new("RGBA", description.size, description.background)
        draw = ImageDraw.Draw(canvas, mode="RGBA")
        for primitive in description.primitives:
            if isinstance(primitive, RasterPrimitive):
                rendered = self._strip_image_cache.get(primitive.cache_key)
                if rendered is None:
                    rendered = _resize_rgba(primitive.array, primitive.rect[2:])
                    if primitive.cache_key is not None:
                        self._strip_image_cache[primitive.cache_key] = rendered
                canvas.alpha_composite(rendered, dest=primitive.rect[:2])
            elif isinstance(primitive, RectanglePrimitive):
                if primitive.fill is not None and primitive.fill[3] < 255:
                    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                    ImageDraw.Draw(overlay, mode="RGBA").rectangle(
                        primitive.box,
                        fill=primitive.fill,
                        outline=primitive.outline,
                        width=primitive.width,
                    )
                    canvas.alpha_composite(overlay)
                else:
                    draw.rectangle(
                        primitive.box,
                        fill=primitive.fill,
                        outline=primitive.outline,
                        width=primitive.width,
                    )
            elif isinstance(primitive, LinePrimitive):
                draw.line(primitive.xy, fill=primitive.fill, width=primitive.width)
            elif primitive.outlined:
                self._draw_outlined_text(canvas, primitive)
            else:
                draw.text(
                    primitive.xy,
                    primitive.text,
                    font=_font(primitive.font_size),
                    fill=primitive.fill,
                    anchor=primitive.anchor,
                )
        return canvas

    @staticmethod
    def _save(array, image, savename, description):
        """Save raster formats directly and PDF through its hybrid renderer."""
        extension = Path(savename).suffix.lower()
        if extension == ".pdf":
            from .pdfexport import export_composition_pdf

            export_composition_pdf(description, image.dpi, savename)
        else:
            Image.fromarray(array, mode="RGBA").save(savename)

    def describe(self, image: ImageSettings, *, additive=False) -> CompositionDescription:
        """Build the shared arrays, geometry, annotations, and coordinate mapping."""
        if not image.elements:
            raise ValueError("No elements to compose")

        elements = sorted(image.elements.items())
        element_shapes = np.array([element.data.shape for _, element in elements], dtype=int)
        layer_keys, layers = self._layers(elements)
        merged_height, merged_width = element_shapes.max(axis=0)
        merged = None if additive else self.merged_image(image, layers)
        geometry = self._layout_geometry(
            image,
            element_shapes,
            (merged_height, merged_width),
        )
        font_size = image.fontsize * image.dpi / 72
        label_dx = int(round(0.012 * geometry.width))
        label_dy = int(round(0.016 * geometry.height))
        image_colors = image.colorscheme.colors()
        foreground_color = image.panelLabelColor
        primitives = []

        if image.layout != Layouts.MERGED:
            border_width = int(image.borderWidth)
            element_border_width = (border_width + 1) // 3
            for index, (x, y, (slot, element)) in enumerate(
                zip(geometry.element_x, geometry.element_y, elements, strict=True)
            ):
                layer = layers[slot]
                height, width = layer.shape
                primitives.append(
                    RasterPrimitive(
                        layer,
                        (x, y, width, height),
                        cache_key=layer_keys[slot],
                    )
                )
                if image.elementBorders and element_border_width > 0:
                    primitives.append(
                        RectanglePrimitive(
                            (
                                x - element_border_width,
                                y - element_border_width,
                                x + width + element_border_width - 1,
                                y + height + element_border_width - 1,
                            ),
                            outline=_rgb255(image_colors[slot]),
                            width=element_border_width,
                        )
                    )
                if image.panelLabels:
                    primitives.append(
                        TextPrimitive(
                            (x + label_dx, y + label_dy),
                            chr(ord("A") + index),
                            font_size * 1.2,
                            _rgb255(foreground_color),
                            "la",
                            outlined=True,
                        )
                    )
                if image.elementLabels:
                    color = image_colors[slot] if image.elementLabelsColored else foreground_color
                    primitives.append(
                        TextPrimitive(
                            (x + width - label_dx, y + label_dy),
                            element.name,
                            font_size,
                            _rgb255(color),
                            "ra",
                            outlined=True,
                        )
                    )

        merged_rect = (
            geometry.merged_x,
            geometry.merged_y,
            geometry.merged_width,
            geometry.merged_height,
        )
        if additive:
            primitives.append(
                RectanglePrimitive(
                    (
                        geometry.merged_x,
                        geometry.merged_y,
                        geometry.merged_x + geometry.merged_width - 1,
                        geometry.merged_y + geometry.merged_height - 1,
                    ),
                    fill=(0, 0, 0, 255),
                )
            )
            colors = image.colorscheme.colors()[[slot for slot, _element in elements]].copy()
            if not image.clipColors:
                maximum = colors.sum(axis=0)
                maximum[maximum <= 0] = 1
                colors /= maximum
            for (slot, _element), color in zip(elements, colors, strict=True):
                layer = layers[slot]
                primitives.append(
                    ColoredRasterPrimitive(
                        layer,
                        (
                            geometry.merged_x,
                            geometry.merged_y,
                            geometry.merged_width * layer.shape[1] / merged_width,
                            geometry.merged_height * layer.shape[0] / merged_height,
                        ),
                        tuple(float(value) for value in color),
                    )
                )
        else:
            primitives.append(RasterPrimitive(merged, merged_rect))
        if image.panelLabels and image.layout != Layouts.MERGED:
            primitives.append(
                TextPrimitive(
                    (geometry.merged_x + label_dx, geometry.merged_y + label_dy),
                    chr(ord("A") + len(elements)),
                    font_size * 1.2,
                    _rgb255(foreground_color),
                    "la",
                    outlined=True,
                ),
            )
        primitives.extend(self._scale_bar_primitives(image, geometry, font_size))

        mapping = ComposedImageMapping(
            x=geometry.merged_x,
            y=geometry.merged_y,
            width=geometry.merged_width,
            height=geometry.merged_height,
            source_x=_nearest_lookup(merged_width, geometry.merged_width),
            source_y=_nearest_lookup(merged_height, geometry.merged_height),
        )
        return CompositionDescription(
            size=(geometry.width, geometry.height),
            background=_rgb255(image.borderColor),
            primitives=tuple(primitives),
            mapping=mapping,
        )

    def compose(self, image: ImageSettings, savename=None):
        """Compose and optionally save an exact-size RGBA image."""
        description = self.describe(image)
        result = np.asarray(self._render_description(description), dtype=np.uint8).copy()
        if savename is not None:
            self._save(result, image, savename, description)

        self.coord_mapping = description.mapping
        return result
