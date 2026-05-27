#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 26 18:34:33 2026

@author: carl
"""
from silx.gui.plot.PlotWidget import PlotWidget

class ExhalePlotWidget(PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent, backend="opengl")
