#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 13 19:21:19 2026

@author: carl
"""

import os.path

class FileSettings:
    def __init__(self, name : str, h5file = None):
        self.name = name
        self.h5file = h5file
        self.alias = os.path.splitext(os.path.basename(name))[0]

    def is_open(self):
        return self.h5file is not None

    def set_h5file(self, h5file):
        self.h5file = h5file

    # def open_h5(self):
    #     if self.h5file is not None:
    #         return True
    #     self.h5file = ...


