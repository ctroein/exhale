#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 14:43:38 2026

@author: carl
"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Any

from .elementsettings import Normalizers
from .imagesettings import ImageSettings, Layouts, Colorschemes, Scalebars

PROJECT_FORMAT = "exhale-project"
PROJECT_VERSION = 1


def _path_to_json(path: tuple[str, str]) -> dict[str, str]:
    return {"file": path[0], "dataset": path[1]}


def _path_from_json(obj: dict[str, str]) -> tuple[str, str]:
    return (obj["file"], obj["dataset"])


def _elementsettings_to_json(es) -> dict[str, Any]:
    return {
        "path": _path_to_json(es.path),
        "name": es.name,
        "normalizer": es.normalizer.name,
        "gamma": es.gamma,
        "trf_range": list(es.trfRange),
    }


def _apply_elementsettings_json(es, obj: dict[str, Any]) -> None:
    es.name = obj["name"]
    es.normalizer = Normalizers[obj["normalizer"]]
    es.gamma = obj["gamma"]
    es.trfRange = list(obj["trf_range"])


def _imagesettings_to_json(img_id: int, im: ImageSettings) -> dict[str, Any]:
    elements = {
        str(slot): _elementsettings_to_json(es)
        for slot, es in im.elements.items()
    }

    return {
        "id": img_id,
        "name": im.name,
        "layout": im.layout.name,
        "scalebar": im.scalebar.name,
        "scalebar_color": list(im.scalebarColor),
        "scalebar_bg_color": list(im.scalebarBgColor),
        "scalebar_bg_alpha": im.scalebarBgAlpha,
        "fontsize": im.fontsize,
        "border_color": list(im.borderColor),
        "border_width": im.borderWidth,
        "panel_labels": im.panelLabels,
        "element_labels": im.elementLabels,
        "colorscheme": im.colorscheme.name,
        "custom_colors": (
            None if im.customColors is None else im.customColors.tolist()
        ),
        "dpi": im.dpi,
        "clip_colors": im.clipColors,
        "resolution": list(im.resolution),
        "elements": elements,
    }


def _imagesettings_from_json(obj: dict[str, Any], win) -> ImageSettings:
    from .elementsettings import ElementSettings
    import numpy as np

    im = ImageSettings(obj["name"])
    im.layout = Layouts[obj["layout"]]
    im.scalebar = Scalebars[obj["scalebar"]]
    im.scalebarColor = list(obj["scalebar_color"])
    im.scalebarBgColor = list(obj["scalebar_bg_color"])
    im.scalebarBgAlpha = obj["scalebar_bg_alpha"]
    im.fontsize = obj["fontsize"]
    im.borderColor = obj["border_color"]
    im.borderWidth = obj["border_width"]
    im.panelLabels = obj["panel_labels"]
    im.elementLabels = obj["element_labels"]
    im.colorscheme = Colorschemes[obj["colorscheme"]]
    im.customColors = obj["custom_colors"]
    im.dpi = obj["dpi"]
    im.clipColors = obj.get("clip_colors", True)
    im.resolution = list(obj["resolution"])

    if im.customColors is not None:
        im.customColors = np.array(im.customColors)
        if im.colorscheme == Colorschemes.CUSTOM:
            im.colorscheme.update(im.customColors)

    for slot_s, es_obj in obj["elements"].items():
        slot = int(slot_s)
        path = _path_from_json(es_obj["path"])
        filename, h5path = path

        fs = win.fileSettings.get(filename)
        if fs is None or fs.h5file is None:
            continue

        ds = fs.h5file[h5path]
        es = ElementSettings(ds)   # fresh copy for this image slot
        _apply_elementsettings_json(es, es_obj)
        im.elements[slot] = es

    return im

def export_project_state(win) -> dict[str, Any]:
    """
    Build a JSON-serializable project-state dict from ExhaleWindow.
    """
    files = []
    for filename, fs in win.fileSettings.items():
        files.append({
            "filename": filename,
            "alias": fs.alias,
        })

    elements = []
    for path, es in win.elementSettings.items():
        elements.append(_elementsettings_to_json(es))

    selected_elements = [
        _path_to_json(path)
        for path in sorted(win.selectedElements)
    ]

    images = []
    for img_id, im in sorted(win.imageSettings.items()):
        images.append(_imagesettings_to_json(img_id, im))

    analysis_options = {
        "nuclei_expansion": win.nucleiExpansion.value(),
        "nuclei_min_area": win.nucleiMinArea.value(),
        "cluster_min_k": win.clusterMinK.value(),
        "cluster_max_k": win.clusterMaxK.value(),
        "cluster_n_init": win.clusterNInit.value(),
    }

    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "files": files,
        "elements": elements,
        "selected_elements": selected_elements,
        "images": images,
        "analysis_options": analysis_options,
    }


def save_project(win, filename: str | Path) -> None:
    """
    Save current project state to JSON.
    """
    filename = Path(filename)
    state = export_project_state(win)
    with filename.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_project_state(win, state: dict[str, Any], *, open_files: bool = True) -> None:
    """
    Restore a saved project into ExhaleWindow.

    Assumes `win` is an ExhaleWindow-like object with the same attributes
    and helper methods as your current code.
    """
    if state.get("format") != PROJECT_FORMAT:
        raise ValueError(f"Not an {PROJECT_FORMAT!r} file")
    version = state.get("version")
    if version != PROJECT_VERSION:
        raise ValueError(
            f"Unsupported project version {version}, expected {PROJECT_VERSION}"
        )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    filenames = [f["filename"] for f in state["files"]]
    if open_files and filenames:
        win.open_files(filenames)

    # Restore aliases after files are known
    for fobj in state["files"]:
        filename = fobj["filename"]
        alias = fobj["alias"]
        if filename in win.fileSettings:
            win.fileSettings[filename].alias = alias

    # ------------------------------------------------------------------
    # Element settings
    # ------------------------------------------------------------------
    # Ensure all referenced elements exist
    for eobj in state["elements"]:
        path = _path_from_json(eobj["path"])

        from .elementsettings import ElementSettings
        filename, h5path = path
        fs = win.fileSettings.get(filename)
        if fs is None or fs.h5file is None:
            continue
        ds = fs.h5file[h5path]
        win.elementSettings[path] = ElementSettings(ds)
        _apply_elementsettings_json(win.elementSettings[path], eobj)

    # ------------------------------------------------------------------
    # Selected elements
    # ------------------------------------------------------------------
    win.selectedElements.clear()
    for pobj in state["selected_elements"]:
        path = _path_from_json(pobj)
        if path in win.elementSettings:
            win.selectedElements.add(path)

    # Let UI rebuild its lists/dropdowns from the new selectedElements
    win.selectedElementsChanged.emit()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    win.imageSettings.clear()
    win.imageList.clear()

    for iobj in state["images"]:
        img_id = iobj["id"]
        im = _imagesettings_from_json(iobj, win)
        win.imageSettings[img_id] = im
        win.imageList.addImage(img_id, im)

    # ------------------------------------------------------------------
    # Analysis options
    # ------------------------------------------------------------------
    a = state["analysis_options"]
    win.nucleiExpansion.setValue(a["nuclei_expansion"])
    win.nucleiMinArea.setValue(a["nuclei_min_area"])
    win.clusterMinK.setValue(a["cluster_min_k"])
    win.clusterMaxK.setValue(a["cluster_max_k"])
    win.clusterNInit.setValue(a["cluster_n_init"])

    # ------------------------------------------------------------------
    # Refresh visible UI
    # ------------------------------------------------------------------
    # Loaded-file alias UI
    if win.loadedFileComboBox.count() > 0:
        win.loadedFileChanged()

    # Pick a sensible current image if any exist
    if win.imageList.count() > 0:
        win.imageList.setCurrentRow(0)


def load_project(win, filename: str | Path, *, open_files: bool = True) -> None:
    filename = Path(filename)
    with filename.open("r", encoding="utf-8") as f:
        state = json.load(f)
    load_project_state(win, state, open_files=open_files)

