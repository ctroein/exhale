"""Image display in array coordinates, independent of composition and storage."""

import math

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets

from .. import icons
from ..tooltips import IMAGE_CANVAS_FIT
from ..widgets import IconToolButton
from .imagecomposer import (
    ColoredRasterPrimitive,
    LinePrimitive,
    RasterPrimitive,
    RectanglePrimitive,
    TextPrimitive,
    _outline_color,
)


def _qcolor(rgba):
    return QtGui.QColor(*rgba)


class _CompositionTextItem(QtWidgets.QGraphicsPathItem):
    """Scene-scaled text using the composition's pixel coordinates."""

    def __init__(self, primitive):
        super().__init__()
        self._fill = QtGui.QColor()
        self._outline = None
        self._outline_width = 0
        self.update_primitive(primitive)

    def update_primitive(self, primitive):
        font = QtGui.QFont(primitive.font_family)
        font.setPixelSize(max(1, round(primitive.font_size)))
        metrics = QtGui.QFontMetricsF(font)
        path = QtGui.QPainterPath()
        path.addText(0, metrics.ascent(), font, primitive.text)
        self.prepareGeometryChange()
        self.setPath(path)
        self._fill = _qcolor(primitive.fill)
        self._outline = None
        self._outline_width = 0
        if primitive.outlined:
            outline = _outline_color(np.array(primitive.fill[:3]) / 255.0)
            self._outline = _qcolor(outline)
            self._outline_width = 2 * max(1, round(0.06 * primitive.font_size))
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))

        bounds = path.boundingRect()
        horizontal = primitive.anchor[0]
        x = primitive.xy[0]
        if horizontal == "l":
            x -= bounds.left()
        elif horizontal == "r":
            x -= bounds.right()
        else:
            x -= bounds.center().x()
        # Pillow's ``a`` anchor places y on the font ascender line rather than
        # at the visible glyph top.  The path baseline is already one ascent
        # below its origin, so retaining y reproduces that vertical spacing.
        self.setPos(x, primitive.xy[1])

    def boundingRect(self):
        bounds = self.path().boundingRect()
        margin = self._outline_width / 2
        return bounds.adjusted(-margin, -margin, margin, margin)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self._outline is not None:
            pen = QtGui.QPen(self._outline, self._outline_width)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
            painter.drawPath(self.path())
        painter.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        painter.setBrush(self._fill)
        painter.drawPath(self.path())


class _CompositionBorderItem(QtWidgets.QGraphicsPathItem):
    """A rectangular pixel band with square inner and outer corners."""

    def __init__(self, primitive):
        super().__init__()
        self.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        self.update_primitive(primitive)

    def update_primitive(self, primitive):
        x0, y0, x1, y1 = primitive.box
        width = primitive.width
        outer_width = x1 - x0 + 1
        outer_height = y1 - y0 + 1
        path = QtGui.QPainterPath()
        path.addRect(QtCore.QRectF(x0, y0, outer_width, width))
        path.addRect(QtCore.QRectF(x0, y1 - width + 1, outer_width, width))
        inner_height = max(0, outer_height - 2 * width)
        if inner_height:
            path.addRect(QtCore.QRectF(x0, y0 + width, width, inner_height))
            path.addRect(QtCore.QRectF(x1 - width + 1, y0 + width, width, inner_height))
        self.setPath(path)
        self.setBrush(_qcolor(primitive.outline))


class ImageViewBox(pg.ViewBox):
    """Square pixels with x rightward and y downward from the top left."""

    def __init__(self):
        super().__init__(lockAspect=True, invertY=True, enableMenu=False, defaultPadding=0)
        self.setMouseMode(self.PanMode)
        self.full_image_rect = None
        self._constraining_range = False

    def setRange(self, *args, **kwargs):
        super().setRange(*args, **kwargs)
        self._constrain_to_image()

    def _constrain_to_image(self):
        """Keep the visible range at or inside the fitted image range."""
        if self.full_image_rect is None or self._constraining_range:
            return

        ranges = self.viewRange()
        spans = [limits[1] - limits[0] for limits in ranges]
        image_spans = [self.full_image_rect.width(), self.full_image_rect.height()]
        if min(spans) <= 0 or min(image_spans) <= 0:
            return

        view_aspect = spans[0] / spans[1]
        image_aspect = image_spans[0] / image_spans[1]
        if view_aspect >= image_aspect:
            fitted_spans = [image_spans[1] * view_aspect, image_spans[1]]
        else:
            fitted_spans = [image_spans[0], image_spans[0] / view_aspect]

        if spans[0] > fitted_spans[0]:
            spans = fitted_spans

        image_limits = [
            (self.full_image_rect.left(), self.full_image_rect.right()),
            (self.full_image_rect.top(), self.full_image_rect.bottom()),
        ]
        constrained = []
        for limits, span, image_span in zip(ranges, spans, image_spans, strict=True):
            image_min, image_max = image_limits[len(constrained)]
            if span >= image_span:
                center = (image_min + image_max) / 2
                constrained.append((center - span / 2, center + span / 2))
            else:
                minimum = min(max(limits[0], image_min), image_max - span)
                constrained.append((minimum, minimum + span))

        if all(
            np.allclose(old, new, rtol=1e-12, atol=1e-12)
            for old, new in zip(ranges, constrained, strict=True)
        ):
            return
        self._constraining_range = True
        try:
            super().setRange(xRange=constrained[0], yRange=constrained[1], padding=0)
        finally:
            self._constraining_range = False


class ImageCanvas(pg.GraphicsLayoutWidget):
    """Display a single array or a scene of native-resolution composition layers.

    Pixel (row, column) occupies [column, column+1) x [row, row+1).
    Single-image mode owns a copy; composition descriptions retain their arrays.
    """

    pixelHovered = QtCore.Signal(object)
    pixelClicked = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.reload_appearance()
        self.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.view_box = ImageViewBox()
        self.addItem(self.view_box)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.view_box.addItem(self.image_item)
        self._composition_items = []
        self._composition_mode = False
        self.composition_description = None
        self.view_box.disableAutoRange()
        self.scene().sigMouseMoved.connect(self._mouse_moved)
        self.scene().sigMouseClicked.connect(self._mouse_clicked)

        self.fit_button = IconToolButton(icons.IconName.MAXIMIZE, self)
        self.fit_button.setToolTip(IMAGE_CANVAS_FIT)
        self.fit_button.setAutoRaise(True)
        self.fit_button.clicked.connect(self.fit_image)
        self._place_fit_button()

    def reload_appearance(self):
        """Apply the current application palette to the canvas."""
        self.setBackground(QtWidgets.QApplication.palette().window().color())
        if hasattr(self, "fit_button"):
            self.fit_button.reload_icon()

    def _place_fit_button(self):
        """Keep the fit control inside the canvas's upper-right corner."""
        if not hasattr(self, "fit_button"):
            return
        margin = 6
        self.fit_button.adjustSize()
        self.fit_button.move(self.width() - self.fit_button.width() - margin, margin)
        self.fit_button.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_fit_button()

    def set_image(self, data, *, reset_view=False):
        """Set a 2-D map in [0, 1] or an (H, W, 4) uint8 composed image.

        Fit the first image, or when explicitly requested. Updating the image
        otherwise preserves the view, including when its dimensions change.
        """
        data = np.asarray(data)
        grayscale = data.ndim == 2 and data.dtype.kind in "buif"
        rgba = data.ndim == 3 and data.shape[2] == 4 and data.dtype == np.uint8
        if not (grayscale or rgba) or not all(data.shape[:2]):
            raise ValueError("Expected a nonempty 2-D grayscale or uint8 RGBA image")
        first_image = self.view_box.full_image_rect is None
        self._clear_composition_items()
        self._composition_mode = False
        self.composition_description = None
        self.image_item.setImage(
            np.array(data, copy=True, order="C"),
            autoLevels=False,
            levels=(0, 1) if grayscale else None,
        )
        height, width = data.shape[:2]
        self.image_item.setRect(QtCore.QRectF(0, 0, width, height))
        self.image_item.setZValue(0)
        self.view_box.full_image_rect = self.image_item.boundingRect()
        if first_image or reset_view:
            self.fit_image()
        else:
            self.view_box._constrain_to_image()

    def set_composition(self, description, *, reset_view=False):
        """Display native rasters and annotations from a composition description."""
        first_image = self.view_box.full_image_rect is None
        previous = self.composition_description
        reusable = (
            self._composition_mode
            and previous is not None
            and tuple(self._composition_kind(primitive) for primitive in previous.primitives)
            == tuple(self._composition_kind(primitive) for primitive in description.primitives)
        )

        if reusable:
            background = self._composition_items[0]
            background.setRect(QtCore.QRectF(0, 0, *description.size))
            background.setBrush(_qcolor(description.background))
            for item, primitive in zip(
                self._composition_items[1:], description.primitives, strict=True
            ):
                self._update_composition_item(item, primitive)
        else:
            self._clear_composition_items()
            self.image_item.clear()
            background = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(0, 0, description.size[0], description.size[1])
            )
            background.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
            background.setBrush(_qcolor(description.background))
            background.setZValue(-1)
            self.view_box.addItem(background)
            self._composition_items.append(background)

            for z_value, primitive in enumerate(description.primitives):
                item = self._composition_item(primitive)
                item.setZValue(z_value)
                self.view_box.addItem(item)
                self._composition_items.append(item)

        self._composition_mode = True
        self.composition_description = description
        bounds = QtCore.QRectF(0, 0, description.size[0], description.size[1])
        self.view_box.full_image_rect = bounds
        if first_image or reset_view:
            self.fit_image()
        else:
            self.view_box._constrain_to_image()

    @staticmethod
    def _composition_kind(primitive):
        if isinstance(primitive, RectanglePrimitive):
            return (RectanglePrimitive, primitive.outline is not None and primitive.fill is None)
        return type(primitive)

    @staticmethod
    def _colored_lut(color):
        levels = np.linspace(0, 1, 256)[:, None]
        rgb = np.asarray(color)[None, :]
        lut = np.empty((256, 4), dtype=np.uint8)
        lut[:, :3] = np.round(255 * levels * rgb).astype(np.uint8)
        lut[:, 3] = 255
        return lut

    def _update_composition_item(self, item, primitive):
        if isinstance(primitive, ColoredRasterPrimitive):
            item.setLookupTable(self._colored_lut(primitive.color))
            item.setImage(np.asarray(primitive.array), autoLevels=False, levels=(0, 1))
            item.setRect(QtCore.QRectF(*primitive.rect))
        elif isinstance(primitive, RasterPrimitive):
            item.setImage(np.asarray(primitive.array), autoLevels=False, levels=(0, 1))
            item.setRect(QtCore.QRectF(*primitive.rect))
        elif isinstance(item, _CompositionBorderItem):
            item.update_primitive(primitive)
        elif isinstance(primitive, RectanglePrimitive):
            x0, y0, x1, y1 = primitive.box
            item.setRect(QtCore.QRectF(x0, y0, x1 - x0 + 1, y1 - y0 + 1))
            item.setBrush(
                _qcolor(primitive.fill)
                if primitive.fill is not None
                else QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)
            )
            item.setPen(
                QtGui.QPen(_qcolor(primitive.outline), primitive.width)
                if primitive.outline is not None
                else QtGui.QPen(QtCore.Qt.PenStyle.NoPen)
            )
        elif isinstance(primitive, LinePrimitive):
            start, end = primitive.xy
            item.setLine(QtCore.QLineF(QtCore.QPointF(*start), QtCore.QPointF(*end)))
            item.setPen(QtGui.QPen(_qcolor(primitive.fill), primitive.width))
        elif isinstance(primitive, TextPrimitive):
            item.update_primitive(primitive)
        else:
            raise TypeError(f"Unsupported composition primitive: {type(primitive)!r}")

    def _composition_item(self, primitive):
        if isinstance(primitive, ColoredRasterPrimitive):
            item = pg.ImageItem(axisOrder="row-major")
            item.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Plus)
            self._update_composition_item(item, primitive)
            return item
        if isinstance(primitive, RasterPrimitive):
            item = pg.ImageItem(axisOrder="row-major")
            self._update_composition_item(item, primitive)
            return item
        if isinstance(primitive, RectanglePrimitive):
            if primitive.outline is not None and primitive.fill is None:
                return _CompositionBorderItem(primitive)
            item = QtWidgets.QGraphicsRectItem()
            self._update_composition_item(item, primitive)
            return item
        if isinstance(primitive, LinePrimitive):
            item = QtWidgets.QGraphicsLineItem()
            self._update_composition_item(item, primitive)
            return item
        if isinstance(primitive, TextPrimitive):
            return _CompositionTextItem(primitive)
        raise TypeError(f"Unsupported composition primitive: {type(primitive)!r}")

    def _clear_composition_items(self):
        for item in self._composition_items:
            self.view_box.removeItem(item)
        self._composition_items.clear()

    def fit_image(self):
        """Show the complete image at square-pixel aspect ratio."""
        if self.view_box.full_image_rect is not None:
            self.view_box.setRange(self.view_box.full_image_rect, padding=0)

    def _pan(self, x_fraction=0, y_fraction=0):
        """Move by a fraction of the currently visible data range."""
        x_range, y_range = self.view_box.viewRange()
        self.view_box.translateBy(
            x=x_fraction * (x_range[1] - x_range[0]), y=y_fraction * (y_range[1] - y_range[0])
        )

    def _zoom(self, factor):
        """Zoom around the centre of the current view."""
        self.view_box.scaleBy((factor, factor))

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Home:
            self.fit_image()
        elif key == QtCore.Qt.Key.Key_Left:
            self._pan(x_fraction=-0.1)
        elif key == QtCore.Qt.Key.Key_Right:
            self._pan(x_fraction=0.1)
        elif key == QtCore.Qt.Key.Key_Up:
            self._pan(y_fraction=-0.1)
        elif key == QtCore.Qt.Key.Key_Down:
            self._pan(y_fraction=0.1)
        elif key in (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal):
            self._zoom(0.8)
        elif key == QtCore.Qt.Key.Key_Minus:
            self._zoom(1.25)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def clear_image(self):
        """Discard the image; the next image starts fitted to the canvas."""
        self._clear_composition_items()
        self._composition_mode = False
        self.composition_description = None
        self.image_item.clear()
        self.view_box.full_image_rect = None

    def pixel_at_scene(self, scene_position):
        """Return the image pixel under a scene position as ``(x, y)``.

        Mapping through the ImageItem makes this independent of the current
        pan, zoom, widget size, and display-pixel ratio.
        """
        if self.view_box.full_image_rect is None:
            return None
        position = (
            self.view_box.mapSceneToView(scene_position)
            if self._composition_mode
            else self.image_item.mapFromScene(scene_position)
        )
        x_position = position.x()
        y_position = position.y()
        # Graphics transforms can return 22.999999999999996 for an exact
        # boundary at 23. Snap only floating-point noise at integer edges.
        if math.isclose(x_position, round(x_position), abs_tol=1e-12):
            x_position = round(x_position)
        if math.isclose(y_position, round(y_position), abs_tol=1e-12):
            y_position = round(y_position)
        x = math.floor(x_position)
        y = math.floor(y_position)
        if self._composition_mode:
            width = round(self.view_box.full_image_rect.width())
            height = round(self.view_box.full_image_rect.height())
        else:
            height, width = self.image_item.image.shape[:2]
        if 0 <= x < width and 0 <= y < height:
            return x, y
        return None

    def pixel_at_viewport(self, viewport_position):
        """Return the image pixel under a viewport position as ``(x, y)``."""
        return self.pixel_at_scene(self.mapToScene(viewport_position))

    def _mouse_moved(self, scene_position):
        self.pixelHovered.emit(self.pixel_at_scene(scene_position))

    def _mouse_clicked(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.pixelClicked.emit(self.pixel_at_scene(event.scenePos()))

    def leaveEvent(self, event):
        self.pixelHovered.emit(None)
        super().leaveEvent(event)
