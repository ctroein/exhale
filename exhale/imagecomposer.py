#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb  6 13:46:40 2026

@author: carl
"""
from .imagesettings import ImageSettings, Layouts, Colorschemes, Scalebars
from silx.gui.plot import PlotWidget
# from silx.gui import qt
# import silx.gui
import numpy as np
from pathlib import Path
from PIL import Image
# import numpy as np

import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Rectangle
from matplotlib import patheffects
from matplotlib_scalebar.scalebar import ScaleBar

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


    def compose(self, image: ImageSettings, savename=None):
        """
        Compose image and return an RGBA uint8 array with exact pixel size.
        """
        if not image.elements:
            raise ValueError("No elements to compose")

        elems = sorted(image.elements.items())
        eshapes = np.array([e.data.shape for i, e in elems])

        merged = ImageComposer.merged_image(image)
        mh, mw, _ = merged.shape
        bw = image.borderWidth

        mscale = 1
        if image.layout in (Layouts.IL, Layouts.IR):
            strip_w = eshapes[:, 1].max()
            strip_h = eshapes[:, 0].sum() + bw * (len(elems) - 1)
            mscale = strip_h / mh
            merged_w = int(round(mw * mscale))
            merged_h = strip_h
            W = strip_w + merged_w + 3 * bw
            H = strip_h + 2 * bw
            exs = [bw] * len(elems)
            if image.layout == Layouts.IR:
                exs = W - bw - eshapes[:, 1]
            eys = np.cumsum(eshapes[:, 0] + bw) - eshapes[0, 0]
        elif image.layout in (Layouts.IA, Layouts.IB):
            strip_w = eshapes[:, 1].sum() + bw * (len(elems) - 1)
            strip_h = eshapes[:, 0].max()
            mscale = strip_w / mw
            merged_w = strip_w
            merged_h = int(round(mh * mscale))
            W = strip_w + 2 * bw
            H = strip_h + merged_h + 3 * bw
            eys = [bw] * len(elems)
            if image.layout == Layouts.IA:
                eys = H - bw - eshapes[:, 0]
            exs = np.cumsum(eshapes[:, 1] + bw) - eshapes[0, 1]
        elif image.layout == Layouts.MERGED:
            merged_w, merged_h = mw, mh
            W, H = mw + 2 * bw, mh + 2 * bw
            exs, eys = [], []
        else:
            # TODO: Layouts without merged image
            raise NotImplementedError(image.layout)

        bgcolor = image.borderColor
        # fgcolor = 1 - np.array(bgcolor)
        fgcolor = image.panelLabelColor
        screen_dpi = 100
        fig = plt.Figure((W / screen_dpi, H / screen_dpi), dpi=screen_dpi,
                         facecolor=bgcolor)
        fig.set_canvas(FigureCanvasAgg(fig))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.axis("off")

        imcolors = image.colorscheme.colors()
        fontsize = (H * image.fontsize) / 500
        labelshift = [.012, .016]
        _LUMA = np.array([0.2126, 0.7152, 0.0722])
        def luma(rgb):
            rgb = np.array(rgb)
            L = np.where(rgb <= 0.04045, rgb / 12.92,
                         ((rgb + 0.055) / 1.055) ** 2.4) * _LUMA
            return L.sum()
        def outline_by_color(rgb):
            L = luma(rgb)
            ffg = [0., 0., 0., .6]
            if L < .05:
                ffg = [1., 1., 1., .6]
            elif L < .12:
                ffg = list(np.array(rgb) / 2) + [.6]
            return [patheffects.Stroke(linewidth=.2*fontsize, foreground=ffg),
                patheffects.Normal()]

        for i, (x, y, (eix, e)) in enumerate(zip(exs, eys, elems)):
            im = e.transformedData()
            h, w = im.shape
            ax.imshow(im, origin="lower", cmap="gray",
                      extent=(x, x + w, y + h, y),
                      interpolation="nearest")
            if image.elementBorders and bw >= 3:
                ebw = bw // 3
                ax.add_patch(Rectangle(
                    (x - ebw//2, y - ebw//2), w + ebw, h + ebw,
                    linewidth=ebw, edgecolor=imcolors[eix], facecolor="none"))
            if image.panelLabels:
                fig.text(
                    x / W + labelshift[0], 1 - y / H - labelshift[1],
                    chr(ord('A') + i),
                    fontsize=fontsize * 1.2, va="top", color=fgcolor,
                    path_effects=outline_by_color(fgcolor))
            if image.elementLabels:
                ecolor = (imcolors[eix] if image.elementLabelsColored
                          else fgcolor)
                fig.text(
                    (x + w) / W - labelshift[0], 1 - y / H - labelshift[1],
                    e.name, fontsize=fontsize, va="top", ha="right",
                    color=ecolor, path_effects=outline_by_color(ecolor))

        mx, my = bw, bw
        if image.layout == Layouts.IL:
            mx = 2 * bw + strip_w
        elif image.layout == Layouts.IB:
            my = 2 * bw + strip_h
        mext = (mx, mx + merged_w, my + merged_h, my)
        ax.imshow(merged, origin="lower", extent=mext,
                  interpolation="nearest")
        if image.panelLabels:
            fig.text(
                mx / W + labelshift[0], 1 - my / H - labelshift[1],
                chr(ord('A') + len(elems)),
                fontsize=fontsize * 1.2, va="top", color=fgcolor,
                path_effects=outline_by_color(fgcolor))

        # ax.add_patch(Rectangle(
        #     (mx - bw//2, my - bw//2), merged_w + bw, merged_h + bw,
        #     linewidth=bw, edgecolor=image.borderColor, facecolor="none"))

        if image.scalebar != Scalebars.NONE:
            # mrect = np.array((mx + bw//2, my + bw//2,
            #                   merged_w - bw, merged_h - bw)) / (W, H, W, H)
            mrect = np.array((mx, my, merged_w, merged_h)) / (W, H, W, H)
            m_ax = fig.add_axes(mrect)
            m_ax.set_xlim(0, merged_w)
            m_ax.set_ylim(merged_h, 0)
            m_ax.set_aspect(1)
            m_ax.axis("off")
            mlocs = {Scalebars.LL: "lower left", Scalebars.LR: "lower right",
                 Scalebars.UL: "upper left", Scalebars.UR: "upper right",}

            # print("COLOR", image.scalebarColor, image.scalebarBgColor, image.scalebarBgAlpha)
            dx, units = image.resolution
            if dx is not None and dx > 0 and units != "None":
                scalebar = ScaleBar(
                    dx=dx/mscale, units=units,
                    location=mlocs[image.scalebar],
                    color=image.scalebarColor,
                    box_color=image.scalebarBgColor,
                    box_alpha=image.scalebarBgAlpha,
                    frameon=image.scalebarBgAlpha is not None,
                    scale_loc='bottom',
                    border_pad=.5,
                    font_properties={'size': fontsize})
                m_ax.add_artist(scalebar)

        fig.canvas.draw()
        buf = np.asarray(fig.canvas.buffer_rgba()).copy()

        if savename is not None:
            ext = Path(savename).suffix.lower()
            img = Image.fromarray(buf, mode="RGBA")

            if ext == ".png":
                img.save(savename)
            elif ext == ".pdf":
                # Flatten alpha onto the chosen background first
                bg = tuple(int(255 * c) for c in image.borderColor)
                flat = Image.new("RGB", img.size, bg)
                flat.paste(img, mask=img.getchannel("A"))
                flat.save(savename, resolution=float(image.dpi))
            else:
                # fallback for other raster formats
                img.save(savename)
            # No longer used:
            # fig.savefig(savename, facecolor=bgcolor)

        self.coord_mapping = (mx, my, merged_w, merged_h, mh, mw)
        return buf


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
                "Postscript (*.ps *.eps)",
                "TIFF (*.tif *.tiff)",
                "SVG (*.svg)",
                "JPEG (*.jpg *.jpeg)",
                "All files (*)"]
