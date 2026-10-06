"""Runtime package information for the About dialog."""

from __future__ import annotations

import sys
from html import escape
from importlib import metadata

from qtpy import API_NAME, QtCore

_PACKAGE_DISTRIBUTIONS = (
    ("QtPy", "QtPy"),
    ("NumPy", "numpy"),
    ("SciPy", "scipy"),
    ("pandas", "pandas"),
    ("h5py", "h5py"),
    ("tifffile", "tifffile"),
    ("Pillow", "Pillow"),
    ("PyQtGraph", "pyqtgraph"),
    ("napari", "napari"),
    ("TensorFlow", "tensorflow"),
    ("StarDist", "stardist"),
)


def _distribution_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unavailable"


def runtime_environment() -> tuple[tuple[str, str], ...]:
    """Return noteworthy runtime components and their detected versions."""
    entries = [
        ("Python", sys.version.split()[0]),
        ("Qt", QtCore.qVersion()),
        (API_NAME, _distribution_version(API_NAME)),
    ]
    entries.extend(
        (label, _distribution_version(distribution))
        for label, distribution in _PACKAGE_DISTRIBUTIONS
    )
    return tuple(entries)


def runtime_environment_html(columns: int = 3) -> str:
    """Format runtime information as a compact fixed-column HTML table."""
    entries = runtime_environment()
    rows = []
    for offset in range(0, len(entries), columns):
        cells = []
        for column, (name, package_version) in enumerate(entries[offset : offset + columns]):
            spacing = "" if column == 0 else "&nbsp;&nbsp;&nbsp;&nbsp;"
            cells.append(f"<td>{spacing}<b>{escape(name)}</b>&nbsp;{escape(package_version)}</td>")
        cells.extend("<td></td>" for _ in range(columns - len(cells)))
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<table width="100%" cellspacing="0" cellpadding="0">{"".join(rows)}</table>'
