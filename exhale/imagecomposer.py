#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb  6 13:46:40 2026

@author: carl
"""
from .imagesettings import ImageSettings, Layouts, Colorschemes, Scalebars
from silx.gui.plot import PlotWidget
from silx.gui import qt
import silx.gui
import numpy as np

# import matplotlib
# matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Rectangle
from matplotlib_scalebar.scalebar import ScaleBar

def merged_image(image : ImageSettings):
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

# def compose_image_old(plot : PlotWidget, image : ImageSettings):
#     "Compose element image with the given elements, layout, colors etc."
#     plot.clear()
#     if not image.elements:
#         return

#     plot.setDataBackgroundColor(silx.gui.colors.asQColor(image.borderColor))
#     m = merged_image(image)
#     if image.layout == Layouts.MERGED:
#         plot.addImage(m, legend='m', origin=(0, 0), copy=False,
#                       replace=True)
#         plot.setLimits(0, m.shape[1], 0, m.shape[0])
#         return

#     elems = image.elements.values()
#     if image.layout.value < Layouts.SQUARES.value:
#         bw = image.borderWidth
#         h = int(image.layout == Layouts.IL or image.layout == Layouts.IR)
#         r = -1 if image.layout in [Layouts.IR, Layouts.IA] else 1
#         hws = np.array([e.data.shape for e in elems])
#         msize = m.shape * len(elems)
#         # Size of entire area
#         totsize = [0, 0]
#         totsize[1-h] = hws[:, 1-h].sum() + bw * (len(elems) + 1)
#         totsize[h] = hws[:, h].max() + msize[h] + 3 * bw

#         pos = np.array([0, 0])
#         offs = [0, 0]
#         pos[h] = totsize[h] if r < 0 else bw
#         for i, e in enumerate(elems):
#             pos[h] += r * bw
#             data = e.transformedData()
#             orig = pos if r > 0 else pos - data.shape[::-1]
#             print("origin/pos",orig,pos)
#             plot.addImage(data, origin=list(orig), copy=False, legend=f'{i}')
#             pos[h] += r * data.shape[1-h]
#         pos[1-h] = bw if r < 0 else totsize[h] - msize[h] - bw
#         pos[h] = (bw * (len(elems) + 1)) // 2
#         print("merged at",pos)
#         plot.addImage(m, legend='m', origin=list(pos), copy=False, scale=len(elems))
#         print("totsize",totsize)
#         plot.setLimits(0, totsize[0], 0, totsize[1])

#         # plot.resetZoom()

#         # if image.scalebar.value:
#         #     boffs = m.shape * len(elems) * .05
#         #     bpos = 111


def compose_image(image: ImageSettings, savename=None):
    """
    Compose image and return an RGBA uint8 array with exact pixel size.
    """
    if not image.elements:
        raise ValueError("No elements to compose")

    elems = list(image.elements.values())
    eshapes = np.array([e.data.shape for e in elems])

    merged = merged_image(image)
    mh, mw, _ = merged.shape
    bw = image.borderWidth
    bc = image.borderColor

    exs = [bw] * len(elems)
    eys = [bw] * len(elems)
    mscale = 1
    if image.layout in (Layouts.IL, Layouts.IR):
        strip_w = eshapes[:, 1].max()
        strip_h = eshapes[:, 0].sum() + bw * (len(elems) - 1)
        mscale = strip_h / mh
        merged_w = int(round(mw * mscale))
        merged_h = strip_h
        W = strip_w + merged_w + 3 * bw
        H = strip_h + 2 * bw
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
        if image.layout == Layouts.IA:
            eys = H - bw - eshapes[:, 0]
        exs = np.cumsum(eshapes[:, 1] + bw) - eshapes[0, 1]
    elif image.layout == Layouts.MERGED:
        merged_w, merged_h = mw, mh
        W, H = mw + 2 * bw, mh + 2 * bw
        # rgb = np.clip(merged * 255, 0, 255).astype(np.uint8)
        # alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
        # return np.concatenate([rgb, alpha], axis=2)
    else:
        raise NotImplementedError(image.layout)

    dpi = image.dpi
    # fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi)
    fig = plt.Figure((W / dpi, H / dpi), dpi=dpi)
    fig.set_canvas(FigureCanvasAgg(fig))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    if image.layout in (Layouts.IL, Layouts.IR, Layouts.IA, Layouts.IB):
        for i, e in enumerate(elems):
            im = e.transformedData()
            h, w = im.shape
            x, y = exs[i], eys[i]
            ax.imshow(im, origin="lower", cmap="gray",
                      extent=(x, x + w, y + h, y),
                      interpolation="nearest")
            ax.add_patch(Rectangle((x - bw//2, y - bw//2), w + bw, h + bw,
                         linewidth=bw, edgecolor=bc, facecolor="none"))

    mx, my = bw, bw
    if image.layout == Layouts.IL:
        mx = 2 * bw + strip_w
    elif image.layout == Layouts.IB:
        my = 2 * bw + strip_h
    mext = (mx, mx + merged_w, my + merged_h, my)
    ax.imshow(merged, origin="lower", extent=mext,
              interpolation="nearest")
    ax.add_patch(Rectangle(
        (mx - bw//2, my - bw//2), merged_w + bw, merged_h + bw,
        linewidth=bw, edgecolor=bc, facecolor="none"))

    if image.scalebar != Scalebars.NONE:
        mrect = np.array((mx + bw//2, my + bw//2,
                          merged_w - bw, merged_h - bw)) / (W, H, W, H)
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
                dx=dx * mscale, units=units,
                location=mlocs[image.scalebar],
                color=image.scalebarColor,
                box_color=image.scalebarBgColor,
                box_alpha=image.scalebarBgAlpha,
                frameon=image.scalebarBgAlpha is not None,
                scale_loc='bottom',
                border_pad=.5,
                font_properties={'size': (H * image.fontsize) / 500})
            m_ax.add_artist(scalebar)

    fig.canvas.draw()
    if savename is not None:
        fig.savefig(savename)
    buf = np.asarray(fig.canvas.buffer_rgba()).copy()
    if buf.shape != (H, W, 4):
        print("Buffer size mismatch", buf.shape, (H, W, 4))
    if savename is not None:
        from PIL import Image
        img = Image.fromarray(buf, mode="RGBA")
        img.save(savename+"_buf.png")
    # plt.close(fig)
    return buf


def plot_composed_image(plot: PlotWidget, image: ImageSettings):
    "Render composed image into a silx PlotWidget"
    plot.clear()
    if not image.elements:
        return
    rgba = compose_image(image)
    plot.addImage(rgba[::-1], origin=(0, 0), scale=(1, 1),
                  legend="c", copy=False, replace=True)
    plot.setLimits(0, rgba.shape[1], 0, rgba.shape[0])
