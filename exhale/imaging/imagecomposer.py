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


@dataclass
class _DrawingContext:
    """Pillow objects and shared presentation values for one composition."""

    canvas: Image.Image
    draw: ImageDraw.ImageDraw
    font: ImageFont.ImageFont
    panel_font: ImageFont.ImageFont
    font_size: float
    label_dx: int
    label_dy: int
    image_colors: np.ndarray
    foreground_color: np.ndarray


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
        rgba = self.compose(image)
        canvas.set_image(rgba, reset_view=reset_view)

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

    def _strip_images(self, elements, layer_keys, layers):
        """Return cached Pillow images for the individual element panels."""
        images = {}
        for slot, _element in elements:
            key = layer_keys[slot]
            if key not in self._strip_image_cache:
                layer = layers[slot]
                self._strip_image_cache[key] = _resize_rgba(layer, (layer.shape[1], layer.shape[0]))
            images[slot] = self._strip_image_cache[key]
        return images

    @staticmethod
    def _drawing_context(image, geometry):
        """Create the canvas and shared drawing resources."""
        canvas = Image.new(
            "RGBA",
            (geometry.width, geometry.height),
            _rgb255(image.borderColor),
        )
        font_size = image.fontsize * image.dpi / 72
        return _DrawingContext(
            canvas=canvas,
            draw=ImageDraw.Draw(canvas, mode="RGBA"),
            font=_font(font_size),
            panel_font=_font(font_size * 1.2),
            font_size=font_size,
            label_dx=int(round(0.012 * geometry.width)),
            label_dy=int(round(0.016 * geometry.height)),
            image_colors=image.colorscheme.colors(),
            foreground_color=image.panelLabelColor,
        )

    @staticmethod
    def _draw_text(context, xy, text, font, fill, anchor=None, stroke_scale=0.06):
        """Draw outlined text onto the composition canvas."""
        stroke_width = max(1, int(round(stroke_scale * font.size)))
        overlay = Image.new("RGBA", context.canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay, mode="RGBA")
        outline = _outline_color(np.array(fill[:3]) / 255.0)
        x, y = xy
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx * dx + dy * dy <= stroke_width * stroke_width:
                    overlay_draw.text(
                        (x + dx, y + dy),
                        text,
                        font=font,
                        fill=outline,
                        anchor=anchor,
                    )
        overlay_draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        context.canvas.alpha_composite(overlay)

    def _draw_element_strip(self, image, elements, layers, strip_images, geometry, context):
        """Draw individual element panels, borders, and labels."""
        if image.layout == Layouts.MERGED:
            return
        border_width = int(image.borderWidth)
        for index, (x, y, (slot, element)) in enumerate(
            zip(geometry.element_x, geometry.element_y, elements, strict=True)
        ):
            layer = layers[slot]
            height, width = layer.shape
            context.canvas.alpha_composite(strip_images[slot], dest=(x, y))

            element_border_width = (border_width + 1) // 3
            if image.elementBorders and element_border_width > 0:
                context.draw.rectangle(
                    [
                        x - element_border_width,
                        y - element_border_width,
                        x + width + element_border_width - 1,
                        y + height + element_border_width - 1,
                    ],
                    outline=_rgb255(context.image_colors[slot]),
                    width=element_border_width,
                )

            if image.panelLabels:
                self._draw_text(
                    context,
                    (x + context.label_dx, y + context.label_dy),
                    chr(ord("A") + index),
                    context.panel_font,
                    _rgb255(context.foreground_color),
                    anchor="la",
                )
            if image.elementLabels:
                color = (
                    context.image_colors[slot]
                    if image.elementLabelsColored
                    else context.foreground_color
                )
                self._draw_text(
                    context,
                    (x + width - context.label_dx, y + context.label_dy),
                    element.name,
                    context.font,
                    _rgb255(color),
                    anchor="ra",
                )

    @staticmethod
    def _draw_scale_bar(image, geometry, context):
        """Draw a physical scale bar when resolution and placement permit it."""
        if image.scalebar == Scalebars.NONE:
            return
        resolution, units = image.resolution
        if resolution is None or resolution <= 0 or units == "None":
            return

        target_length = (geometry.merged_width / geometry.merged_scale) * resolution * 0.20
        physical_length = _nice_number(target_length)
        if physical_length <= 0:
            return

        bar_width = int(round((physical_length / resolution) * geometry.merged_scale))
        bar_width = max(8, min(bar_width, int(0.8 * geometry.merged_width)))
        line_width = max(2, int(round(context.font_size * 0.18)))
        padding = max(4, int(round(context.font_size * 0.7)))
        text_gap = max(2, int(round(context.font_size * 0.25)))
        label = _format_length(physical_length, units)
        bbox = context.draw.textbbox((0, 0), label, font=context.font)
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

        if image.scalebarBgAlpha is not None:
            box_x0 = min(x0, x0 + (bar_width - text_width) // 2) - padding // 2
            box_x1 = max(x1, x0 + (bar_width + text_width) // 2) + padding // 2
            box_y0 = min(text_y, line_y) - padding // 2
            box_y1 = max(text_y + text_height, line_y + line_width) + padding // 2
            overlay = Image.new("RGBA", context.canvas.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay, mode="RGBA")
            overlay_draw.rectangle(
                [box_x0, box_y0, box_x1, box_y1],
                fill=_rgb255(
                    image.scalebarBgColor,
                    alpha=int(round(255 * image.scalebarBgAlpha)),
                ),
            )
            context.canvas.alpha_composite(overlay)

        color = _rgb255(image.scalebarColor)
        context.draw.line(
            [(x0, line_y), (x1, line_y)],
            fill=color,
            width=line_width,
        )
        context.draw.text(
            (x0 + bar_width // 2, text_y),
            label,
            font=context.font,
            fill=color,
            anchor="ma",
        )

    @staticmethod
    def _save(array, image, savename):
        """Save the composed array, flattening transparency for PDF output."""
        extension = Path(savename).suffix.lower()
        output = Image.fromarray(array, mode="RGBA")
        if extension == ".pdf":
            background = tuple(int(255 * value) for value in np.clip(image.borderColor, 0, 1))
            flattened = Image.new("RGB", output.size, background)
            flattened.paste(output, mask=output.getchannel("A"))
            flattened.save(savename, resolution=float(image.dpi))
        else:
            output.save(savename)

    def compose(self, image: ImageSettings, savename=None):
        """Compose and optionally save an exact-size RGBA image."""
        if not image.elements:
            raise ValueError("No elements to compose")

        elements = sorted(image.elements.items())
        element_shapes = np.array([element.data.shape for _, element in elements], dtype=int)
        layer_keys, layers = self._layers(elements)
        merged = self.merged_image(image, layers)
        merged_height, merged_width, _channels = merged.shape
        geometry = self._layout_geometry(
            image,
            element_shapes,
            (merged_height, merged_width),
        )
        strip_images = self._strip_images(elements, layer_keys, layers)
        context = self._drawing_context(image, geometry)

        self._draw_element_strip(
            image,
            elements,
            layers,
            strip_images,
            geometry,
            context,
        )
        context.canvas.alpha_composite(
            _resize_rgba(merged, (geometry.merged_width, geometry.merged_height)),
            dest=(geometry.merged_x, geometry.merged_y),
        )
        if image.panelLabels:
            self._draw_text(
                context,
                (
                    geometry.merged_x + context.label_dx,
                    geometry.merged_y + context.label_dy,
                ),
                chr(ord("A") + len(elements)),
                context.panel_font,
                _rgb255(context.foreground_color),
                anchor="la",
            )
        self._draw_scale_bar(image, geometry, context)

        result = np.asarray(context.canvas, dtype=np.uint8).copy()
        if savename is not None:
            self._save(result, image, savename)

        self.coord_mapping = ComposedImageMapping(
            x=geometry.merged_x,
            y=geometry.merged_y,
            width=geometry.merged_width,
            height=geometry.merged_height,
            source_x=_nearest_lookup(merged_width, geometry.merged_width),
            source_y=_nearest_lookup(merged_height, geometry.merged_height),
        )
        return result
