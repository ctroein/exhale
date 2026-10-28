#!/usr/bin/env python3
"""Application identity, version, and packaged resource location."""

import re
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from importlib.resources import files
from pathlib import Path


def _version_from_git(repository: Path) -> str | None:
    """Return a concise version for a source checkout, if Git can describe it."""
    if not (repository / ".git").exists():
        return None
    try:
        description = subprocess.run(
            ["git", "-C", str(repository), "describe", "--tags", "--long", "--dirty"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None

    match = re.fullmatch(r"(.+)-(\d+)-g[0-9a-f]+(-dirty)?", description)
    if match is None:
        return None
    tag, commits, dirty = match.groups()
    tag = tag.removeprefix("v")
    return tag if commits == "0" and dirty is None else f"{tag}-dev"


exhale_version = _version_from_git(Path(__file__).resolve().parent.parent)
if exhale_version is None:
    try:
        exhale_version = package_version("exhale-lung")
    except PackageNotFoundError:
        exhale_version = "dev"

application_name = "Exhale"
application_description = "Efficient X-ray Hub Aiding Lung Explorations"
application_title = f"{application_name} {exhale_version}"
resdir = files("exhale").joinpath("resources")
application_icon_filename = "xrf.png"
