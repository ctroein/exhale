"""Publication rendering for labelled matrix plots."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from qtpy import QtCore, QtGui, QtSvg

from ..data.plotsettings import MatrixPlotSettings, MatrixPublicationSettings
from .matrixplots import MatrixPlotSpec, MatrixTextLayout, matrix_text_layout

POINTS_PER_MM = 72.0 / 25.4


@dataclass(frozen=True)
class MatrixPdfLayout:
    """Tight matrix-export geometry, expressed in typographic points."""

    page_width: float
    page_height: float
    matrix: QtCore.QRectF
    cell_size: float
    row_label_width: float
    column_label_height: float
    color_bar: QtCore.QRectF | None
    color_bar_label_x: float | None
    color_bar_ticks_x: float | None
    text: MatrixTextLayout

    @property
    def width_mm(self) -> float:
        return self.page_width / POINTS_PER_MM

    @property
    def height_mm(self) -> float:
        return self.page_height / POINTS_PER_MM


@dataclass(frozen=True)
class MatrixExportOutcome:
    """Report the effective export choices without changing saved settings."""

    layout: MatrixPdfLayout
    font_size: float
    decimals: int
    adjustments: tuple[str, ...]


def _font(settings: MatrixPublicationSettings) -> QtGui.QFont:
    font = QtGui.QFont(settings.font_family) if settings.font_family else QtGui.QFont()
    font.setPixelSize(max(1, round(settings.font_size)))
    return font


def _measured_text(spec: MatrixPlotSpec, publication: MatrixPublicationSettings):
    font = _font(publication)
    metrics = QtGui.QFontMetricsF(font)
    return replace(
        matrix_text_layout(
            spec,
            metrics.height(),
            metrics.horizontalAdvance,
            em_size=font.pixelSize(),
        ),
        page_padding=0.0,
    )


def minimum_matrix_dimensions_mm(
    spec: MatrixPlotSpec,
    publication: MatrixPublicationSettings,
    settings: MatrixPlotSettings,
) -> tuple[float, float]:
    """Return the smallest page dimensions that preserve readable cells."""
    text = _measured_text(spec, publication)
    color_bar_side = text.color_bar_side_width if settings.color_bar_position != "hidden" else 0.0
    count = len(spec.labels)
    width = 2 * text.page_padding + text.row_label_width + color_bar_side
    top_text = text.font_height / 2 if settings.color_bar_position != "hidden" else 0.0
    height = 2 * text.page_padding + top_text + text.column_label_height
    return (
        (width + count * text.minimum_cell) / POINTS_PER_MM,
        (height + count * text.minimum_cell) / POINTS_PER_MM,
    )


def matrix_pdf_layout(
    spec: MatrixPlotSpec,
    publication: MatrixPublicationSettings,
    settings: MatrixPlotSettings,
) -> MatrixPdfLayout:
    """Calculate a tight layout within the requested maximum dimensions."""
    if not spec.labels:
        raise ValueError("The matrix has no labels to export")
    text = _measured_text(spec, publication)
    color_bar_side = text.color_bar_side_width if settings.color_bar_position != "hidden" else 0.0
    count = len(spec.labels)
    static_width = 2 * text.page_padding + text.row_label_width + color_bar_side
    top_text = text.font_height / 2 if settings.color_bar_position != "hidden" else 0.0
    static_height = 2 * text.page_padding + top_text + text.column_label_height
    fixed_width = None if settings.width_mm is None else settings.width_mm * POINTS_PER_MM
    fixed_height = None if settings.height_mm is None else settings.height_mm * POINTS_PER_MM
    width_cell = None if fixed_width is None else (fixed_width - static_width) / count
    height_cell = None if fixed_height is None else (fixed_height - static_height) / count
    candidates = [value for value in (width_cell, height_cell) if value is not None]
    cell_size = min(candidates) if candidates else text.preferred_cell
    if cell_size < text.minimum_cell:
        raise ValueError(
            "The figure size is too small for the matrix contents at the current font size."
        )

    natural_width = static_width + count * cell_size
    natural_height = static_height + count * cell_size
    page_width = natural_width if fixed_width is None else fixed_width
    page_height = natural_height if fixed_height is None else fixed_height
    content_x = (page_width - natural_width) / 2
    content_y = (page_height - natural_height) / 2
    if settings.color_bar_position == "left":
        matrix_left = content_x + text.page_padding + color_bar_side + text.row_label_width
        bar_left = content_x + text.page_padding
    else:
        matrix_left = content_x + text.page_padding + text.row_label_width
        bar_left = matrix_left + count * cell_size + text.color_bar_matrix_gap
    tick_x = bar_left + text.color_bar_width + text.color_bar_tick_gap
    label_x = bar_left + text.color_bar_width + text.color_bar_label_offset
    matrix = QtCore.QRectF(
        matrix_left,
        content_y + text.page_padding + top_text,
        count * cell_size,
        count * cell_size,
    )
    color_bar = None
    if settings.color_bar_position != "hidden":
        color_bar = QtCore.QRectF(bar_left, matrix.top(), text.color_bar_width, matrix.height())
    return MatrixPdfLayout(
        page_width,
        page_height,
        matrix,
        cell_size,
        text.row_label_width,
        text.column_label_height,
        color_bar,
        label_x if color_bar is not None else None,
        tick_x if color_bar is not None else None,
        text,
    )


def prepare_matrix_export(
    spec: MatrixPlotSpec,
    publication: MatrixPublicationSettings,
    settings: MatrixPlotSettings,
) -> tuple[MatrixPlotSpec, MatrixPublicationSettings, MatrixExportOutcome]:
    """Fit an export, reducing precision and font only for this rendering."""
    decimals = spec.decimals
    font_size = publication.font_size
    last_error = None
    decimal_choices = range(decimals, -1, -1) if spec.show_values else (decimals,)
    for candidate_decimals in decimal_choices:
        candidate_spec = replace(spec, decimals=candidate_decimals)
        try:
            layout = matrix_pdf_layout(candidate_spec, publication, settings)
        except ValueError as error:
            last_error = error
        else:
            adjustments = ()
            if candidate_decimals != decimals:
                adjustments = (f"decimals reduced from {decimals} to {candidate_decimals}",)
            return (
                candidate_spec,
                publication,
                MatrixExportOutcome(layout, font_size, candidate_decimals, adjustments),
            )

    candidate_spec = replace(spec, decimals=0) if spec.show_values else spec
    candidate_size = font_size - 0.5
    while candidate_size >= 4.0:
        candidate_publication = replace(publication, font_size=candidate_size)
        try:
            layout = matrix_pdf_layout(candidate_spec, candidate_publication, settings)
        except ValueError as error:
            last_error = error
            candidate_size -= 0.5
            continue
        adjustments = []
        if candidate_spec.decimals != decimals:
            adjustments.append(f"decimals reduced from {decimals} to {candidate_spec.decimals}")
        adjustments.append(f"font reduced from {font_size:g} pt to {candidate_size:g} pt")
        return (
            candidate_spec,
            candidate_publication,
            MatrixExportOutcome(
                layout, candidate_size, candidate_spec.decimals, tuple(adjustments)
            ),
        )
    assert last_error is not None
    raise last_error


def _interpolated_color(spec: MatrixPlotSpec, value: float) -> QtGui.QColor:
    lower, upper = spec.levels
    position = 0.5 if upper == lower else np.clip((value - lower) / (upper - lower), 0.0, 1.0)
    stops = spec.color_stops
    for first, second in zip(stops, stops[1:], strict=False):
        if position <= second.position:
            span = second.position - first.position
            fraction = 0.0 if span == 0 else (position - first.position) / span
            rgba = [
                round(a + fraction * (b - a))
                for a, b in zip(first.color, second.color, strict=True)
            ]
            return QtGui.QColor(*rgba)
    return QtGui.QColor(*stops[-1].color)


def _contrasting_text(background: QtGui.QColor) -> QtGui.QColor:
    return QtGui.QColor("black" if background.lightnessF() > 0.55 else "white")


def _draw_centered_text(painter, rect: QtCore.QRectF, text: str) -> None:
    painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)


def _draw_color_bar(painter, spec: MatrixPlotSpec, layout: MatrixPdfLayout):
    rect = layout.color_bar
    if rect is None:
        return
    text = layout.text
    gradient = QtGui.QLinearGradient(rect.left(), rect.bottom(), rect.left(), rect.top())
    for stop in spec.color_stops:
        gradient.setColorAt(stop.position, QtGui.QColor(*stop.color))
    painter.fillRect(rect, gradient)
    painter.setPen(QtGui.QPen(QtGui.QColor("black"), 0.5))
    painter.drawRect(rect)

    lower, upper = spec.levels
    tick_x = layout.color_bar_ticks_x
    assert tick_x is not None
    for position in np.linspace(0.0, 1.0, 21):
        value = lower + position * (upper - lower)
        y = rect.bottom() - position * rect.height()
        major = abs(value - lower) < 1e-9 or abs(value - upper) < 1e-9 or abs(value) < 1e-9
        tick_length = text.font_height * (0.3 if major else 0.15)
        painter.drawLine(
            QtCore.QPointF(rect.right(), y), QtCore.QPointF(rect.right() + tick_length, y)
        )
        if not major:
            continue
        text_rect = QtCore.QRectF(
            tick_x,
            y - text.font_height / 2,
            text.color_bar_tick_width,
            text.font_height,
        )
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"{value:g}",
        )

    label_x = layout.color_bar_label_x
    assert label_x is not None
    painter.save()
    painter.translate(label_x + text.color_bar_label_width, rect.center().y())
    painter.rotate(-90)
    label_rect = QtCore.QRectF(
        -rect.height() / 2,
        -text.font_height,
        rect.height(),
        text.font_height,
    )
    _draw_centered_text(painter, label_rect, spec.color_bar_label)
    painter.restore()


def _paint_matrix(
    painter: QtGui.QPainter,
    spec: MatrixPlotSpec,
    publication: MatrixPublicationSettings,
    settings: MatrixPlotSettings,
    layout: MatrixPdfLayout,
) -> None:
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
    font = _font(publication)
    painter.setFont(font)
    metrics = QtGui.QFontMetricsF(font)
    painter.fillRect(
        QtCore.QRectF(0, 0, layout.page_width, layout.page_height), QtGui.QColor("white")
    )
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
    for row, values in enumerate(spec.values):
        for column, value in enumerate(values):
            rect = QtCore.QRectF(
                layout.matrix.left() + column * layout.cell_size,
                layout.matrix.top() + row * layout.cell_size,
                layout.cell_size,
                layout.cell_size,
            )
            color = (
                _interpolated_color(spec, float(value))
                if np.isfinite(value)
                else QtGui.QColor(225, 225, 225)
            )
            painter.fillRect(rect, color)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    for row, values in enumerate(spec.values):
        for column, value in enumerate(values):
            rect = QtCore.QRectF(
                layout.matrix.left() + column * layout.cell_size,
                layout.matrix.top() + row * layout.cell_size,
                layout.cell_size,
                layout.cell_size,
            )
            if spec.show_values and np.isfinite(value):
                color = _interpolated_color(spec, float(value))
                painter.setPen(_contrasting_text(color))
                _draw_centered_text(painter, rect, f"{value:.{spec.decimals}f}")

    painter.setPen(QtGui.QPen(QtGui.QColor("black"), 0.5))
    if settings.cell_borders:
        count = len(spec.labels)
        for index in range(1, count):
            offset = index * layout.cell_size
            painter.drawLine(
                QtCore.QPointF(layout.matrix.left() + offset, layout.matrix.top()),
                QtCore.QPointF(layout.matrix.left() + offset, layout.matrix.bottom()),
            )
            painter.drawLine(
                QtCore.QPointF(layout.matrix.left(), layout.matrix.top() + offset),
                QtCore.QPointF(layout.matrix.right(), layout.matrix.top() + offset),
            )
    painter.drawRect(layout.matrix)

    painter.setPen(QtGui.QColor("black"))
    for index, label in enumerate(spec.labels):
        row_rect = QtCore.QRectF(
            layout.matrix.left() - layout.row_label_width,
            layout.matrix.top() + index * layout.cell_size,
            layout.row_label_width - metrics.height() * 0.3,
            layout.cell_size,
        )
        painter.drawText(
            row_rect,
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        advance = metrics.horizontalAdvance(label)
        rotation = QtGui.QTransform().rotate(-45)
        rotated_top_right = rotation.map(QtCore.QPointF(0, -metrics.ascent()))
        target = QtCore.QPointF(
            layout.matrix.left() + (index + 0.5) * layout.cell_size,
            layout.matrix.bottom() + layout.text.column_label_gap,
        )
        painter.save()
        painter.translate(target - rotated_top_right)
        painter.rotate(-45)
        painter.drawText(QtCore.QPointF(-advance, 0), label)
        painter.restore()
    _draw_color_bar(painter, spec, layout)


def _uniform_page_transform(painter, device_width, device_height, layout):
    scale = min(device_width / layout.page_width, device_height / layout.page_height)
    painter.translate(
        (device_width - layout.page_width * scale) / 2,
        (device_height - layout.page_height * scale) / 2,
    )
    painter.scale(scale, scale)


def export_matrix_pdf(spec, publication, settings, filename) -> MatrixExportOutcome:
    """Render a publication matrix to vector PDF."""
    spec, publication, outcome = prepare_matrix_export(spec, publication, settings)
    layout = outcome.layout
    writer = QtGui.QPdfWriter(str(Path(filename)))
    writer.setResolution(720)
    writer.setPageSize(
        QtGui.QPageSize(
            QtCore.QSizeF(layout.page_width, layout.page_height),
            QtGui.QPageSize.Unit.Point,
            "EXHALE correlation matrix",
            QtGui.QPageSize.SizeMatchPolicy.ExactMatch,
        )
    )
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Unit.Point)
    painter = QtGui.QPainter(writer)
    if not painter.isActive():
        raise OSError(f"Could not create PDF {filename}")
    try:
        rect = writer.pageLayout().paintRectPixels(writer.resolution())
        _uniform_page_transform(painter, rect.width(), rect.height(), layout)
        _paint_matrix(painter, spec, publication, settings, layout)
    finally:
        painter.end()
    return outcome


def export_matrix_png(spec, publication, settings, filename) -> MatrixExportOutcome:
    """Render a publication matrix to a raster image at the selected DPI."""
    spec, publication, outcome = prepare_matrix_export(spec, publication, settings)
    layout = outcome.layout
    scale = settings.dpi / 72.0
    width = max(1, round(layout.page_width * scale))
    height = max(1, round(layout.page_height * scale))
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32)
    dots_per_meter = round(settings.dpi / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)
    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    try:
        _uniform_page_transform(painter, width, height, layout)
        _paint_matrix(painter, spec, publication, settings, layout)
    finally:
        painter.end()
    if not image.save(str(Path(filename)), "PNG"):
        raise OSError(f"Could not create PNG {filename}")
    return outcome


def export_matrix_svg(spec, publication, settings, filename) -> MatrixExportOutcome:
    """Render a publication matrix as native SVG vector shapes and text."""
    spec, publication, outcome = prepare_matrix_export(spec, publication, settings)
    layout = outcome.layout
    coordinate_scale = 100
    pixel_scale = settings.dpi / 72.0
    width = max(1, round(layout.page_width * pixel_scale))
    height = max(1, round(layout.page_height * pixel_scale))
    generator = QtSvg.QSvgGenerator()
    generator.setFileName(str(Path(filename)))
    generator.setTitle("EXHALE correlation matrix")
    generator.setResolution(settings.dpi)
    generator.setSize(QtCore.QSize(width, height))
    generator.setViewBox(
        QtCore.QRect(
            0,
            0,
            round(layout.page_width * coordinate_scale),
            round(layout.page_height * coordinate_scale),
        )
    )
    painter = QtGui.QPainter(generator)
    if not painter.isActive():
        raise OSError(f"Could not create SVG {filename}")
    try:
        painter.scale(coordinate_scale, coordinate_scale)
        _paint_matrix(painter, spec, publication, settings, layout)
    finally:
        painter.end()
    path = Path(filename)
    contents = path.read_text(encoding="utf-8")
    contents = re.sub(
        r'(<svg\s+width=")[^"]+("\s+height=")[^"]+("\s)',
        rf"\g<1>{width}px\g<2>{height}px\g<3>",
        contents,
        count=1,
    )
    path.write_text(contents, encoding="utf-8")
    return outcome
