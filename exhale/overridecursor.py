#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 13:53:44 2026

@author: carl
"""
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication

class OverrideCursor:
    def __init__(self, cursor=Qt.WaitCursor):
        self.cursor = cursor

    def __enter__(self):
        QApplication.setOverrideCursor(self.cursor)

    def __exit__(self, exc_type, exc, tb):
        QApplication.restoreOverrideCursor()
