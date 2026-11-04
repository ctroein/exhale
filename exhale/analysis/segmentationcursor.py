"""Transient Qt brush shading and modifier cursors for the segmentation canvas."""

import numpy as np
from qtpy import QtCore, QtGui, QtWidgets

from ..data.segmentationediting import SegmentationEditSession


def brush_path(shape, position, size):
    """Return the exact clipped brush footprint in image pixel coordinates."""
    position = np.asarray(position, dtype=float)
    center = np.floor(position + 0.5) if size % 2 else np.floor(position) + 0.5
    low = np.maximum(0, np.ceil(center - size / 2).astype(int))
    high = np.minimum(shape, np.floor(center + size / 2).astype(int) + 1)
    path = QtGui.QPainterPath()
    if np.any(high <= low):
        return path
    mask = SegmentationEditSession.brush_mask(high - low, [position - low], size)
    for y, row in enumerate(mask):
        edges = np.diff(np.pad(row.astype(np.int8), 1))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
            path.addRect(
                float(start + low[1] - 0.5), float(y + low[0] - 0.5), float(end - start), 1
            )
    return path.simplified()


class _ModifierKeys(QtCore.QObject):
    """Observe modifier keys while the canvas is visible, without consuming them."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, watched, event):
        self.owner.modifier_event(watched, event)
        return False


class SegmentationCursor(QtWidgets.QWidget):
    """Paint previews above OpenGL without adding layers or altering mask data.

    Mouse events pass through to Napari. Key events are observed within this
    window so modifier cursors also change when the pointer remains stationary.
    """

    def __init__(self, helper):
        self.canvas = helper.qtwidget.canvas.native
        super().__init__(self.canvas)
        self.helper = helper
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setGeometry(self.canvas.rect())
        self._inside = False
        self._position = QtCore.QPointF()
        self._modifiers = QtCore.Qt.NoModifier
        self._path = QtGui.QPainterPath()
        self._base_cursor = None
        self._cursor_update = False
        self._cursors = {}
        self.hide()
        self._key_filter = _ModifierKeys(self)
        self._watching_keys = False
        self.canvas.installEventFilter(self)
        self._watch_modifiers(self.canvas.isVisible())
        camera = getattr(helper.viewer, "scene", helper.viewer).camera
        camera.events.zoom.connect(self.refresh)
        camera.events.center.connect(self.refresh)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.canvas:
            if kind == QtCore.QEvent.Show:
                self._watch_modifiers(True)
            elif kind == QtCore.QEvent.Enter:
                self._inside = True
                self._position = QtCore.QPointF(self.canvas.mapFromGlobal(QtGui.QCursor.pos()))
                self._modifiers = QtWidgets.QApplication.keyboardModifiers()
                self.refresh()
            elif kind in (QtCore.QEvent.Leave, QtCore.QEvent.Hide, QtCore.QEvent.Close):
                if kind != QtCore.QEvent.Leave:
                    self._watch_modifiers(False)
                self._inside = False
                self.refresh()
            elif kind in (
                QtCore.QEvent.MouseMove,
                QtCore.QEvent.MouseButtonPress,
                QtCore.QEvent.MouseButtonRelease,
            ):
                self._position = (
                    event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
                )
                self._inside = self.canvas.rect().contains(self._position.toPoint())
                self._modifiers = event.modifiers()
                self.refresh()
            elif kind == QtCore.QEvent.Resize:
                self.setGeometry(self.canvas.rect())
                self.refresh()
            elif kind == QtCore.QEvent.CursorChange and not self._cursor_update:
                if self._base_cursor is not None:
                    self._base_cursor = self.canvas.cursor()
                self.refresh()
        return False

    def _watch_modifiers(self, enabled):
        """Remove application-wide observation before the canvas is torn down."""
        if enabled != self._watching_keys:
            app = QtWidgets.QApplication.instance()
            if enabled:
                app.installEventFilter(self._key_filter)
            else:
                app.removeEventFilter(self._key_filter)
            self._watching_keys = enabled

    def modifier_event(self, watched, event):
        """Refresh a stationary pointer when modifier keys change in this window."""
        kind = event.type()
        if (
            self._inside
            and kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease)
            and isinstance(watched, QtWidgets.QWidget)
            and watched.window() is self.canvas.window()
        ):
            self._modifiers = event.modifiers()
            modifier = {
                QtCore.Qt.Key_Shift: QtCore.Qt.ShiftModifier,
                QtCore.Qt.Key_Control: QtCore.Qt.ControlModifier,
            }.get(event.key())
            if modifier is not None:
                if kind == QtCore.QEvent.KeyPress:
                    self._modifiers |= modifier
                else:
                    self._modifiers &= ~modifier
            self.refresh()

    def _modifier_cursor(self, symbol):
        ratio = self.canvas.devicePixelRatioF()
        key = symbol, ratio
        if key not in self._cursors:
            pixmap = QtGui.QPixmap(round(32 * ratio), round(32 * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            arrow = QtGui.QPainterPath(QtCore.QPointF(2, 2))
            for x, y in ((2, 20), (7, 15), (11, 24), (15, 22), (11, 14), (18, 14)):
                arrow.lineTo(x, y)
            arrow.closeSubpath()
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.5))
            painter.setBrush(QtCore.Qt.black)
            painter.drawPath(arrow)
            mark = QtGui.QPainterPath(QtCore.QPointF(19, 24))
            mark.lineTo(29, 24)
            if symbol == "+":
                mark.moveTo(24, 19)
                mark.lineTo(24, 29)
            for color, width in ((QtCore.Qt.white, 5), (QtCore.Qt.black, 2)):
                painter.setPen(QtGui.QPen(color, width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
                painter.drawPath(mark)
            painter.end()
            self._cursors[key] = QtGui.QCursor(pixmap, 2, 2)
        return self._cursors[key]

    def _set_cursor(self, symbol):
        self._cursor_update = True
        try:
            if symbol:
                if self._base_cursor is None:
                    self._base_cursor = self.canvas.cursor()
                self.canvas.setCursor(self._modifier_cursor(symbol))
            elif self._base_cursor is not None:
                self.canvas.setCursor(self._base_cursor)
                self._base_cursor = None
        finally:
            self._cursor_update = False

    def refresh(self, _event=None):
        """Refresh the footprint and modifier cursor from current viewer state."""
        active = self._inside and self.helper.edit_session is not None and self.canvas.isVisible()
        tool = self.helper.edit_tool if active else "select"
        symbol = None
        if tool == "draw":
            if self._modifiers & QtCore.Qt.ControlModifier:
                symbol = "−"
            elif self._modifiers & QtCore.Qt.ShiftModifier:
                symbol = "+"
        self._set_cursor(symbol)
        self._path = QtGui.QPainterPath()
        if tool in ("add", "remove") and self.helper.nuc_layer is not None:
            viewer = self.helper.viewer
            layer = self.helper.nuc_layer
            # Derive the 2-D affine map from Napari's public canvas conversion.
            # This includes the camera, axis orientation and layer transforms.
            basis = [
                np.asarray(layer.world_to_data(viewer.canvas_to_world(point)))[-2:]
                for point in ((0, 0), (1, 0), (0, 1))
            ]
            origin = basis[0]
            matrix = np.column_stack((basis[2] - origin, basis[1] - origin))
            inverse = np.linalg.inv(matrix)
            position = origin + matrix @ (self._position.x(), self._position.y())
            path = brush_path(
                self.helper.edit_session.labels.shape, position, self.helper.brush_size
            )
            offset = -inverse @ origin
            transform = QtGui.QTransform(
                inverse[0, 1], inverse[1, 1], inverse[0, 0], inverse[1, 0], offset[0], offset[1]
            )
            self._path = transform.map(path)
        if self._path.isEmpty():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        draw = self.helper.edit_tool == "add"
        painter.setBrush(QtGui.QColor(255, 255, 255, 75) if draw else QtGui.QColor(0, 0, 0, 75))
        painter.setPen(QtGui.QPen(QtCore.Qt.black if draw else QtCore.Qt.white, 1))
        painter.drawPath(self._path)
        painter.end()
