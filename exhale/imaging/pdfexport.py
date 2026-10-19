"""Hybrid PDF rendering for composed images."""

from pathlib import Path

import numpy as np
from qtpy import QtCore, QtGui

from .imagecomposer import (
    LinePrimitive,
    RasterPrimitive,
    RectanglePrimitive,
    TextPrimitive,
    _array_to_rgba,
    _outline_color,
)


def _color(rgba):
    return QtGui.QColor(*rgba)


def _qimage(array):
    rgba = np.ascontiguousarray(_array_to_rgba(array))
    height, width = rgba.shape[:2]
    image = QtGui.QImage(
        rgba.data,
        width,
        height,
        rgba.strides[0],
        QtGui.QImage.Format.Format_RGBA8888,
    )
    return image.copy()


def _draw_rectangle(painter, primitive):
    x0, y0, x1, y1 = primitive.box
    outer_width = x1 - x0 + 1
    outer_height = y1 - y0 + 1
    if primitive.fill is not None:
        painter.fillRect(QtCore.QRectF(x0, y0, outer_width, outer_height), _color(primitive.fill))
    if primitive.outline is None:
        return

    width = primitive.width
    color = _color(primitive.outline)
    painter.fillRect(QtCore.QRectF(x0, y0, outer_width, width), color)
    painter.fillRect(QtCore.QRectF(x0, y1 - width + 1, outer_width, width), color)
    inner_height = max(0, outer_height - 2 * width)
    if inner_height:
        painter.fillRect(QtCore.QRectF(x0, y0 + width, width, inner_height), color)
        painter.fillRect(QtCore.QRectF(x1 - width + 1, y0 + width, width, inner_height), color)


def _text_path(primitive):
    font = QtGui.QFont(primitive.font_family)
    font.setPixelSize(max(1, round(primitive.font_size)))
    metrics = QtGui.QFontMetricsF(font)
    path = QtGui.QPainterPath()
    path.addText(0, metrics.ascent(), font, primitive.text)
    bounds = path.boundingRect()
    horizontal = primitive.anchor[0]
    x = primitive.xy[0]
    if horizontal == "l":
        x -= bounds.left()
    elif horizontal == "r":
        x -= bounds.right()
    else:
        x -= bounds.center().x()
    return path.translated(x, primitive.xy[1])


def _draw_text(painter, primitive):
    path = _text_path(primitive)
    if primitive.outlined:
        outline = _outline_color(np.array(primitive.fill[:3]) / 255.0)
        pen = QtGui.QPen(_color(outline), 2 * max(1, round(0.06 * primitive.font_size)))
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(_color(primitive.fill))
    painter.drawPath(path)


def export_composition_pdf(description, dpi, filename):
    """Write native raster panels with vector annotations to a PDF page."""
    width, height = description.size
    writer = QtGui.QPdfWriter(str(Path(filename)))
    writer.setResolution(round(dpi))
    page_size = QtGui.QPageSize(
        QtCore.QSizeF(width * 25.4 / dpi, height * 25.4 / dpi),
        QtGui.QPageSize.Millimeter,
        "EXHALE composition",
        QtGui.QPageSize.ExactMatch,
    )
    writer.setPageSize(page_size)
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Millimeter)

    painter = QtGui.QPainter(writer)
    if not painter.isActive():
        raise OSError(f"Could not create PDF {filename}")
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.setWindow(0, 0, width, height)
        painter.fillRect(QtCore.QRectF(0, 0, width, height), _color(description.background))

        for primitive in description.primitives:
            if isinstance(primitive, RasterPrimitive):
                painter.drawImage(QtCore.QRectF(*primitive.rect), _qimage(primitive.array))
            elif isinstance(primitive, RectanglePrimitive):
                _draw_rectangle(painter, primitive)
            elif isinstance(primitive, LinePrimitive):
                start, end = primitive.xy
                pen = QtGui.QPen(_color(primitive.fill), primitive.width)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawLine(QtCore.QPointF(*start), QtCore.QPointF(*end))
            elif isinstance(primitive, TextPrimitive):
                _draw_text(painter, primitive)
            else:
                raise TypeError(f"Unsupported PDF primitive: {type(primitive)!r}")
    finally:
        painter.end()
