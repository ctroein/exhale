"""Sample-row dragging independent of file import and file ownership."""

import json

from qtpy import QtCore, QtGui, QtWidgets

from ..widgets import ItemTreeWidget


class SampleTreeWidget(ItemTreeWidget):
    """Move complete sample groups between top-level positions."""

    samplesMoved = QtCore.Signal(object, int)
    MIME_TYPE = "application/x-exhale-sample-order"
    NODE_KIND_ROLE = QtCore.Qt.UserRole
    NODE_ID_ROLE = QtCore.Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._insertion = QtWidgets.QFrame(self.viewport())
        self._insertion.setFrameShape(QtWidgets.QFrame.HLine)
        self._insertion.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._insertion.hide()

    def startDrag(self, supported_actions):
        current = self.currentItem()
        if current is None or current.parent() is not None:
            return
        samples = [
            self.topLevelItem(row).data(0, self.NODE_ID_ROLE)
            for row in range(self.topLevelItemCount())
            if self.topLevelItem(row).isSelected()
        ]
        if not samples:
            return
        mime = QtCore.QMimeData()
        mime.setData(self.MIME_TYPE, json.dumps(samples).encode())
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.MoveAction)
        self._insertion.hide()

    def _internal(self, event):
        return event.source() is self and event.mimeData().hasFormat(self.MIME_TYPE)

    def dragEnterEvent(self, event):
        if self._internal(event):
            event.setDropAction(QtCore.Qt.MoveAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def _drop_position(self, point):
        item = self.itemAt(point)
        if item is None:
            return self.topLevelItemCount()
        if item.parent() is not None:
            while item.parent() is not None:
                item = item.parent()
            return self.indexOfTopLevelItem(item) + 1
        return self.indexOfTopLevelItem(item) + int(
            point.y() >= self.visualItemRect(item).center().y()
        )

    def dragMoveEvent(self, event):
        if not self._internal(event):
            super().dragMoveEvent(event)
            return
        index = self._drop_position(event.position().toPoint())
        if index < self.topLevelItemCount():
            y = self.visualItemRect(self.topLevelItem(index)).top()
        else:
            item = self.topLevelItem(self.topLevelItemCount() - 1)
            while item is not None and self.itemBelow(item) is not None:
                item = self.itemBelow(item)
            y = self.visualItemRect(item).bottom() if item is not None else 0
        self._insertion.setGeometry(0, y - 1, self.viewport().width(), 3)
        self._insertion.show()
        event.setDropAction(QtCore.Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._insertion.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._insertion.hide()
        if not self._internal(event):
            super().dropEvent(event)
            return
        sample_ids = json.loads(bytes(event.mimeData().data(self.MIME_TYPE)))
        self.samplesMoved.emit(sample_ids, self._drop_position(event.position().toPoint()))
        event.setDropAction(QtCore.Qt.MoveAction)
        event.accept()
