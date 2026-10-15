#!/usr/bin/env python3
"""Context-managed access to Qt's application-wide override cursor."""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication


class OverrideCursor:
    """Install an override cursor for the duration of a ``with`` block."""

    def __init__(self, cursor=Qt.WaitCursor):
        self.cursor = cursor

    def __enter__(self):
        QApplication.setOverrideCursor(self.cursor)

    def __exit__(self, exc_type, exc, tb):
        QApplication.restoreOverrideCursor()
