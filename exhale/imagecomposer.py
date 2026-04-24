#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb  6 13:46:40 2026

@author: carl
"""
from .imagesettings import ImageSettings, Layouts, Scalebars
from silx.gui.plot import PlotWidget
import numpy as np
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


class ImageComposer():
    "Functionality for making a nice image out of element maps"
    def __init__(self):
        self.coord_mapping = None

    @staticmethod
    def merged_image(image: ImageSettings):
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
            td = es.transformedData()
            h, w = td.shape
            merged[:h, :w] = merged[:h, :w] + td[..., None] * colors[i]
        if image.clipColors:
            return np.minimum(merged, 1.)
        return merged / maxcolor

    def plot_composed_image(self, plot: PlotWidget, image: ImageSettings):
        "Render composed image into a silx PlotWidget"
        plot.clear()
        if not image.elements:
            return
        rgba = self.compose(image)
        plot.addImage(rgba[::-1], origin=(0, 0), scale=(1, 1),
                      legend="c", copy=False, replace=True)
        plot.setLimits(0, rgba.shape[1], 0, rgba.shape[0])

    def map_coordinates(self, plot: PlotWidget, x, y):
        "Map plot coordinates to image (array) coordinates"
        if self.coord_mapping is None:
            return None
        mx, my, mwp, mhp, mh, mw = self.coord_mapping
        if not (mx <= x < mx + mwp and my <= y < my + mhp):
            return None
        return int((x - mx) * mw / mwp), int((y - my) * mh / mhp)

    @staticmethod
    def get_format_filters():
        return ["PNG (*.png)",
                "PDF (*.pdf)",
                "TIFF (*.tif *.tiff)",
                "JPEG (*.jpg *.jpeg)",
                "All files (*)"]


    def compose(self, image: ImageSettings, savename=None):
        """
        Compose image and return an RGBA uint8 array with exact pixel size.

        Pillow/NumPy implementation:
        - arrays are pasted directly into a top-left-origin canvas
        - text, borders, and scale bar are drawn with ImageDraw
        - coord_mapping remains compatible with map_coordinates()
        """

        if not image.elements:
            raise ValueError("No elements to compose")

        elems = sorted(image.elements.items())
        eshapes = np.array([e.data.shape for _, e in elems], dtype=int)

        merged = ImageComposer.merged_image(image)
        mh, mw, _ = merged.shape
        bw = int(image.borderWidth)

        # ------------------------------------------------------------
        # Layout: keep the same geometry as the Matplotlib version
        # ------------------------------------------------------------
        mscale = 1.0

        if image.layout in (Layouts.IL, Layouts.IR):
            strip_w = int(eshapes[:, 1].max())
            strip_h = int(eshapes[:, 0].sum() + bw * (len(elems) - 1))

            mscale = strip_h / mh
            merged_w = int(round(mw * mscale))
            merged_h = strip_h

            W = int(strip_w + merged_w + 3 * bw)
            H = int(strip_h + 2 * bw)

            exs = [bw] * len(elems)
            if image.layout == Layouts.IR:
                exs = [int(W - bw - w) for h, w in eshapes]

            eys = (
                np.cumsum(eshapes[:, 0] + bw) - eshapes[0, 0]
            ).astype(int).tolist()

        elif image.layout in (Layouts.IA, Layouts.IB):
            strip_w = int(eshapes[:, 1].sum() + bw * (len(elems) - 1))
            strip_h = int(eshapes[:, 0].max())

            mscale = strip_w / mw
            merged_w = strip_w
            merged_h = int(round(mh * mscale))

            W = int(strip_w + 2 * bw)
            H = int(strip_h + merged_h + 3 * bw)

            eys = [bw] * len(elems)
            if image.layout == Layouts.IB:
                eys = [int(H - bw - h) for h, w in eshapes]

            exs = (
                np.cumsum(eshapes[:, 1] + bw) - eshapes[0, 1]
            ).astype(int).tolist()

        elif image.layout == Layouts.MERGED:
            merged_w, merged_h = int(mw), int(mh)
            W, H = int(mw + 2 * bw), int(mh + 2 * bw)
            exs, eys = [], []

        else:
            raise NotImplementedError(image.layout)

        # ------------------------------------------------------------
        # Helpers
        # ------------------------------------------------------------
        def rgb255(rgb, alpha=255):
            a = np.asarray(rgb, dtype=float)
            a = np.clip(a, 0, 1)
            vals = [int(round(255 * v)) for v in a[:3]]
            return tuple(vals + [int(alpha)])

        def arr_to_rgba(arr):
            arr = np.asarray(arr, dtype=float)
            arr = np.clip(arr, 0, 1)
            if arr.ndim == 2:
                arr = np.repeat(arr[..., None], 3, axis=2)
            alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
            rgb = np.round(arr[..., :3] * 255).astype(np.uint8)
            return np.concatenate([rgb, alpha], axis=2)

        def resize_rgba(arr, size):
            pil = Image.fromarray(arr_to_rgba(arr), mode="RGBA")
            if pil.size != tuple(size):
                pil = pil.resize(tuple(size), resample=Image.Resampling.NEAREST)
            return pil

        def get_font(size):
            size = max(1, int(round(size)))
            for name in ("DejaVuSans.ttf", "Arial.ttf"):
                try:
                    return ImageFont.truetype(name, size=size)
                except OSError:
                    pass
            return ImageFont.load_default()

        _LUMA = np.array([0.2126, 0.7152, 0.0722])

        def luma(rgb):
            rgb = np.asarray(rgb, dtype=float)
            rgb = np.clip(rgb, 0, 1)
            lin = np.where(
                rgb <= 0.04045,
                rgb / 12.92,
                ((rgb + 0.055) / 1.055) ** 2.4,
            )
            return float((lin * _LUMA).sum())

        def outline_color(rgb):
            L = luma(rgb)
            if L < 0.05:
                return rgb255([1, 1, 1], alpha=153)
            if L < 0.12:
                return rgb255(np.asarray(rgb) / 2, alpha=153)
            return rgb255([0, 0, 0], alpha=153)

        def draw_text(draw, xy, text, font, fill, anchor=None, stroke_scale=0.06):
            stroke_width = max(1, int(round(stroke_scale * font.size)))

            # Create transparent overlay
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay, mode="RGBA")

            # Semi-transparent black outline
            # outline = (0, 0, 0, 153)  # 0.6 alpha
            outline = outline_color(np.array(fill[:3]) / 255.0)

            # Draw outline by stamping text in a circle
            x, y = xy
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx*dx + dy*dy <= stroke_width * stroke_width:
                        odraw.text((x + dx, y + dy), text, font=font,
                                   fill=outline, anchor=anchor)

            # Draw main text (opaque) on same overlay
            odraw.text(xy, text, font=font, fill=fill, anchor=anchor)

            # Composite onto canvas
            canvas.alpha_composite(overlay)

        _UNIT_TO_NM = {
            "pm": 1e-3,
            "nm": 1.0,
            "um": 1e3,
            "µm": 1e3,
            "mm": 1e6,
            "cm": 1e7,
        }

        _DISPLAY_UNITS = [
            ("pm", 1e-3),
            ("nm", 1.0),
            ("µm", 1e3),
            ("mm", 1e6),
            ("cm", 1e7),
        ]

        def format_length(value, units):
            """
            Convert a physical length to a suitable display prefix.

            `value` is in the original `units`.
            """
            if units not in _UNIT_TO_NM:
                return f"{value:g} {units}"

            value_nm = value * _UNIT_TO_NM[units]

            chosen_unit, chosen_scale = _DISPLAY_UNITS[0]
            for unit, scale in _DISPLAY_UNITS:
                if value_nm / scale >= 1:
                    chosen_unit, chosen_scale = unit, scale

            shown = value_nm / chosen_scale
            return f"{shown:g} {chosen_unit}"

        def nice_number(x):
            if x <= 0:
                return 0
            exp = math.floor(math.log10(x))
            f = x / (10 ** exp)
            if f < 1.5:
                nf = 1
            elif f < 3.5:
                nf = 2
            elif f < 7.5:
                nf = 5
            else:
                nf = 10
            return nf * (10 ** exp)

        def draw_scale_bar(draw):
            if image.scalebar == Scalebars.NONE:
                return

            dx, units = image.resolution
            if dx is None or dx <= 0 or units == "None":
                return

            # The scalebar must refer to the original input-image pixel size.
            # merged_w / mscale is the corresponding width in original pixels.
            target_phys = (merged_w / mscale) * dx * 0.20
            bar_phys = nice_number(target_phys)
            if bar_phys <= 0:
                return

            bar_px = int(round((bar_phys / dx) * mscale))
            bar_px = max(8, min(bar_px, int(0.8 * merged_w)))

            line_w = max(2, int(round(fontsize * 0.18)))
            pad = max(4, int(round(fontsize * 0.7)))
            text_gap = max(2, int(round(fontsize * 0.25)))
            label = format_length(bar_phys, units)

            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            if image.scalebar in (Scalebars.LL, Scalebars.UL):
                x0 = mx + pad
            else:
                x0 = mx + merged_w - pad - bar_px

            if image.scalebar in (Scalebars.LL, Scalebars.LR):
                y_line = my + merged_h - pad - th - text_gap
                y_text = y_line + text_gap
            else:
                y_text = my + pad
                y_line = y_text + th + text_gap

            x1 = x0 + bar_px

            # Optional background box
            if image.scalebarBgAlpha is not None:
                bx0 = min(x0, x0 + (bar_px - tw) // 2) - pad // 2
                bx1 = max(x1, x0 + (bar_px + tw) // 2) + pad // 2
                by0 = min(y_text, y_line) - pad // 2
                by1 = max(y_text + th, y_line + line_w) + pad // 2

                overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                odraw = ImageDraw.Draw(overlay, mode="RGBA")
                odraw.rectangle(
                    [bx0, by0, bx1, by1],
                    fill=rgb255(
                        image.scalebarBgColor,
                        alpha=int(round(255 * image.scalebarBgAlpha)),
                    ),
                )
                canvas.alpha_composite(overlay)

            color = rgb255(image.scalebarColor)
            draw.line([(x0, y_line), (x1, y_line)], fill=color, width=line_w)

            tx = x0 + bar_px // 2
            draw.text(
                (tx, y_text),
                label,
                font=font,
                fill=color,
                anchor="ma",
            )

        # ------------------------------------------------------------
        # Canvas
        # ------------------------------------------------------------
        canvas = Image.new("RGBA", (W, H), rgb255(image.borderColor))
        draw = ImageDraw.Draw(canvas, mode="RGBA")

        imcolors = image.colorscheme.colors()
        fgcolor = image.panelLabelColor

        fontsize = image.fontsize * image.dpi / 72
        # fontsize = max(1.0, (H * image.fontsize) / 300)
        font = get_font(fontsize)
        panel_font = get_font(fontsize * 1.2)

        labelshift = [0.012, 0.016]
        dx_label = int(round(labelshift[0] * W))
        dy_label = int(round(labelshift[1] * H))

        # ------------------------------------------------------------
        # Element strip
        # ------------------------------------------------------------
        for i, (x, y, (eix, e)) in enumerate(zip(exs, eys, elems)):
            x = int(x)
            y = int(y)

            arr = e.transformedData()
            h, w = arr.shape

            canvas.alpha_composite(resize_rgba(arr, (w, h)), dest=(x, y))

            if image.elementBorders and bw >= 3:
                ebw = max(1, bw // 3)
                gap = 0
                draw.rectangle(
                    [
                        x - ebw - gap,
                        y - ebw - gap,
                        x + w + ebw + gap - 1,
                        y + h + ebw + gap - 1,
                    ],
                    outline=rgb255(imcolors[eix]),
                    width=ebw,
                )

            if image.panelLabels:
                draw_text(
                    draw,
                    (x + dx_label, y + dy_label),
                    chr(ord("A") + i),
                    panel_font,
                    rgb255(fgcolor),
                    anchor="la",
                )

            if image.elementLabels:
                ecolor = imcolors[eix] if image.elementLabelsColored else fgcolor
                draw_text(
                    draw,
                    (x + w - dx_label, y + dy_label),
                    e.name,
                    font,
                    rgb255(ecolor),
                    anchor="ra",
                )

        # ------------------------------------------------------------
        # Merged image
        # ------------------------------------------------------------
        mx, my = bw, bw
        if image.layout == Layouts.IL:
            mx = 2 * bw + strip_w
        elif image.layout == Layouts.IB:
            my = 2 * bw + strip_h

        mx = int(mx)
        my = int(my)

        canvas.alpha_composite(
            resize_rgba(merged, (merged_w, merged_h)),
            dest=(mx, my),
        )

        if image.panelLabels:
            draw_text(
                draw,
                (mx + dx_label, my + dy_label),
                chr(ord("A") + len(elems)),
                panel_font,
                rgb255(fgcolor),
                anchor="la",
            )

        draw_scale_bar(draw)

        # ------------------------------------------------------------
        # Return/save
        # ------------------------------------------------------------
        buf = np.asarray(canvas, dtype=np.uint8).copy()

        if savename is not None:
            ext = Path(savename).suffix.lower()
            img = Image.fromarray(buf, mode="RGBA")

            if ext == ".pdf":
                bg = tuple(int(255 * c) for c in np.clip(image.borderColor, 0, 1))
                flat = Image.new("RGB", img.size, bg)
                flat.paste(img, mask=img.getchannel("A"))
                flat.save(savename, resolution=float(image.dpi))
            else:
                img.save(savename)

        self.coord_mapping = (mx, my, merged_w, merged_h, mh, mw)
        return buf
