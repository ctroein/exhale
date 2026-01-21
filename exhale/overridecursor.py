#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 13:53:44 2026

@author: carl
"""
from silx.gui.qt import Qt, QApplication

class OverrideCursor:
    def __init__(self, cursor=Qt.WaitCursor):
        self.cursor = cursor

    def __enter__(self):
        QApplication.setOverrideCursor(self.cursor)

    def __exit__(self, exc_type, exc, tb):
        QApplication.restoreOverrideCursor()
