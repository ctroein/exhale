"""Palette-aware access to Exhale's bundled icons."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from qtpy import QtCore, QtGui, QtSvg
from qtpy.QtWidgets import QApplication

from . import resdir
from .appearance import is_dark


class IconName(str, Enum):
    LOGO = "xrf_cells_b.png"
    OPEN = "open.svg"
    FOLDER = "folder-open.svg"
    PROJECT = "folder-open.svg"
    CLEAR_FILES = "rays.svg"
    SAVE = "save.svg"
    SAVE_AS = "save-as.svg"
    SETTINGS = "settings.svg"
    INFO = "info-circle.svg"
    QUIT = "x-mark.svg"
    MAXIMIZE = "arrows-maximize.svg"
    DELETE = "trash.svg"
    IMAGE = "photo.svg"
    ADD_IMAGE = "photo-plus.svg"
    ELEMENT = "atom.svg"
    FILE = "file-dots.svg"


_ICON_ROOT = Path(resdir) / "icons"
_cache: dict[IconName, QtGui.QIcon] = {}

class SvgIconEngine(QtGui.QIconEngine):
    def __init__(self, svg):
        super().__init__()
        self._svg = svg
        self._renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        if not self._renderer.isValid():
            raise ValueError("Invalid SVG data")

    def _render(self, size):
        pm = QtGui.QPixmap(size)
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        self._renderer.render(painter)
        painter.end()
        return pm

    @staticmethod
    def _grayscale(pm):
        source = pm.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        grayscale = source.convertToFormat(QtGui.QImage.Format_Grayscale8).convertToFormat(
            QtGui.QImage.Format_ARGB32
        )
        painter = QtGui.QPainter(grayscale)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, source)
        painter.end()
        return QtGui.QPixmap.fromImage(grayscale)

    def pixmap(self, size, mode, state):
        pm = self._render(size)
        if mode == QtGui.QIcon.Disabled:
            pm = self._grayscale(pm)
        return pm

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))

    def clone(self):
        return SvgIconEngine(self._svg)


def svg_icon(path: Path):
    """Create an SVG icon with palette-aware substitutions from file annotations.

    Two annotation forms are recognized::

        <!-- exhale blend [original] [role] #[rrggbb] [fraction] -->
        <!-- exhale dark [original] #[rrggbb] -->

    ``blend`` replaces the original color with a mixture of the named Qt palette
    role and the supplied RGB value. ``dark`` applies its replacement only while
    the application uses a dark palette.

    :param path: SVG resource containing optional Exhale annotations.
    :return: Palette-adjusted scalable icon.
    """

    def blend(a, b, f):
        return QtGui.QColor(
            round((1 - f) * a.red() + f * b.red()),
            round((1 - f) * a.green() + f * b.green()),
            round((1 - f) * a.blue() + f * b.blue()),
        ).name()

    palette = QApplication.instance().palette()
    svg = path.read_text(encoding="utf-8")
    replacements = {}

    if is_dark():
        for replace, color in re.findall(
            r"<!--\s*exhale\s+dark\s+(\S+)\s+(#[0-9a-fA-F]{6})\s*-->", svg
        ):
            replacements[replace] = color

    for replace, role, color, fraction in re.findall(
        r"<!--\s*exhale\s+blend\s+(\S+)\s+(\w+)\s+"
        r"(#[0-9a-fA-F]{6})\s+([0-9.]+)\s*-->",
        svg,
    ):
        replacements[replace] = blend(
            palette.color(getattr(QtGui.QPalette, role)), QtGui.QColor(color), float(fraction)
        )

    # Replace all at the same time
    if replacements:
        pattern = re.compile("|".join(map(re.escape, replacements.keys())))
        svg = pattern.sub(lambda m: replacements[m.group(0)], svg)
    return QtGui.QIcon(SvgIconEngine(svg))


def initialize() -> None:
    """Discard icons generated for the previous application palette."""
    _cache.clear()


def icon(name: IconName) -> QtGui.QIcon:
    """Return a cached, scalable icon for the selected palette."""
    cached = _cache.get(name)
    if cached is not None:
        return cached
    path = _ICON_ROOT / name.value
    if path.suffix.lower() == ".svg":
        loaded = svg_icon(path)
    else:
        loaded = QtGui.QIcon(str(path))
    if loaded.isNull():
        raise ValueError(f"Cannot load icon: {path}")
    _cache[name] = loaded
    return loaded


def icon_pixmap(name: IconName, height: int) -> QtGui.QPixmap:
    """Render an icon at the given height, preserving its aspect ratio."""
    path = _ICON_ROOT / name.value
    if path.suffix.lower() == ".svg":
        source_size = QtSvg.QSvgRenderer(str(path)).defaultSize()
    else:
        source_size = QtGui.QImageReader(str(path)).size()
    if not source_size.isValid() or source_size.height() <= 0:
        raise ValueError(f"Cannot determine icon dimensions: {path}")

    width = round(height * source_size.width() / source_size.height())
    return icon(name).pixmap(width, height)
