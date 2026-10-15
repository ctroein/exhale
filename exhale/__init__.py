#!/usr/bin/env python3
"""Application identity, version, and packaged resource location."""

from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files

try:
    exhale_version = version("exhale-lung")
except PackageNotFoundError:
    exhale_version = "dev"

application_name = "Exhale"
application_description = "Efficient X-ray Hub Aiding Lung Explorations"
application_title = f"{application_name} {exhale_version}"
resdir = files("exhale").joinpath("resources")
