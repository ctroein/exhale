#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 29 12:23:17 2024

@author: carl
"""

from importlib.resources import files
from importlib.metadata import version, PackageNotFoundError


try:
    exhale_version = version("exhale-lung")
except PackageNotFoundError:
    exhale_version = "dev"

application_name = "Exhale"
application_description = "Efficient X-ray Hub Aiding Lung Explorations"
application_title = f"{application_name} {exhale_version}"
resdir = files("exhale").joinpath("resources")
