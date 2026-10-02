"""Image display in array coordinates, independent of composition and storage."""

import math

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets
import pyqtgraph as pg


class ImageViewBox(pg.ViewBox):
    """Square pixels with x rightward and y downward from the top left."""

    def __init__(self):
        super().__init__(lockAspect=True, invertY=True, enableMenu=False,
                         defaultPadding=0)
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
        image_spans = [self.full_image_rect.width(),
                       self.full_image_rect.height()]
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
        for limits, span, image_span in zip(ranges, spans, image_spans):
            image_min, image_max = image_limits[len(constrained)]
            if span >= image_span:
                center = (image_min + image_max) / 2
                constrained.append((center - span / 2, center + span / 2))
            else:
                minimum = min(max(limits[0], image_min), image_max - span)
                constrained.append((minimum, minimum + span))

        if all(np.allclose(old, new, rtol=1e-12, atol=1e-12)
               for old, new in zip(ranges, constrained)):
            return
        self._constraining_range = True
        try:
            super().setRange(
                xRange=constrained[0], yRange=constrained[1], padding=0)
        finally:
            self._constraining_range = False


class ImageCanvas(pg.GraphicsLayoutWidget):
    """Display normalized grayscale or uint8 RGBA arrays without rescaling values.

    Pixel (row, column) occupies [column, column+1) x [row, row+1).
    The canvas owns a copy of its image; callers may reuse their input arrays.
    """

    pixelHovered = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setBackground(QtWidgets.QApplication.palette().window().color())
        self.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.view_box = ImageViewBox()
        self.addItem(self.view_box)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.view_box.addItem(self.image_item)
        self.view_box.disableAutoRange()
        self.scene().sigMouseMoved.connect(self._mouse_moved)

        self.fit_button = QtWidgets.QToolButton(self)
        self.fit_button.setText("Fit")
        self.fit_button.setToolTip("Fit the full image (Home)")
        self.fit_button.setAutoRaise(True)
        self.fit_button.clicked.connect(self.fit_image)
        self._place_fit_button()

    def _place_fit_button(self):
        """Keep the fit control inside the canvas's upper-right corner."""
        if not hasattr(self, "fit_button"):
            return
        margin = 6
        self.fit_button.adjustSize()
        self.fit_button.move(
            self.width() - self.fit_button.width() - margin, margin)
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
        first_image = self.image_item.image is None
        self.image_item.setImage(
            np.array(data, copy=True, order="C"), autoLevels=False,
            levels=(0, 1) if grayscale else None)
        self.view_box.full_image_rect = self.image_item.boundingRect()
        if first_image or reset_view:
            self.fit_image()
        else:
            self.view_box._constrain_to_image()

    def fit_image(self):
        """Show the complete image at square-pixel aspect ratio."""
        if self.image_item.image is not None:
            bounds = self.image_item.boundingRect()
            self.view_box.full_image_rect = bounds
            self.view_box.setRange(bounds, padding=0)

    def _pan(self, x_fraction=0, y_fraction=0):
        """Move by a fraction of the currently visible data range."""
        x_range, y_range = self.view_box.viewRange()
        self.view_box.translateBy(
            x=x_fraction * (x_range[1] - x_range[0]),
            y=y_fraction * (y_range[1] - y_range[0]))

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
        self.image_item.clear()
        self.view_box.full_image_rect = None

    def pixel_at_scene(self, scene_position):
        """Return the image pixel under a scene position as ``(x, y)``.

        Mapping through the ImageItem makes this independent of the current
        pan, zoom, widget size, and display-pixel ratio.
        """
        if self.image_item.image is None:
            return None
        position = self.image_item.mapFromScene(scene_position)
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
        height, width = self.image_item.image.shape[:2]
        if 0 <= x < width and 0 <= y < height:
            return x, y
        return None

    def pixel_at_viewport(self, viewport_position):
        """Return the image pixel under a viewport position as ``(x, y)``."""
        return self.pixel_at_scene(self.mapToScene(viewport_position))

    def _mouse_moved(self, scene_position):
        self.pixelHovered.emit(self.pixel_at_scene(scene_position))

    def leaveEvent(self, event):
        self.pixelHovered.emit(None)
        super().leaveEvent(event)
