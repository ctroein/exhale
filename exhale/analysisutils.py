#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar 27 00:34:39 2026

@author: carl
"""

import os
import numpy as np
import importlib
from .elementsettings import ElementSettings
from silx.gui import qt

def init_libs():
    "Defers loading of TF, stardist and such"
    # Uncomment in case we need to load from . instead of a specified path
    # _cwd = os.getcwd()
    # import exhale.resources
    # os.chdir(next(iter(exhale.resources.__path__)))
    from .xrf_refcopy import xrf_utils
    xrf_utils.load_model(basedir=importlib.resources.files(
        "exhale").joinpath("resources"))
    # os.chdir(_cwd)
    assert xrf_utils.model

def xrf_analysis(nuclei_data: ElementSettings, tissue_data: ElementSettings,
                 elements: list, callback=print):
    init_libs()
    from .xrf_refcopy.xrf_sample_class import XRFSample
    from .xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel

    sample = XRFSample("Default_sample")
    sample.nuclei = NucleiChannel(nuclei_data.data)
    sample.tissue = TissueChannel(tissue_data.data)
    for es in elements:
        sample.add_element(es.name, es.data)

    callback("Preparing to process")
    sample.process(
        cluster_min_k=3,
        cluster_max_k=6,
        cluster_n_init=10)
    callback("Processed; combining")
    sample.combine()
    callback("Analysis ready")
    return sample


def build_tooltip_text(
        label_val: int, region_df, element_names: list[str]) -> str:
    rows = region_df[region_df["label"] == label_val]
    if rows.empty:
        return ""

    text = [f"Label: {label_val}"]
    for elem in element_names:
        row = rows[rows["element"] == elem]
        if row.empty:
            continue
        r = row.iloc[0]
        sizes = ", ".join(f"{v:.0f}" for v in r["cluster_sizes"])
        intensities = ", ".join(f"{v:.3g}" for v in r["cluster_intensities"])
        text.append(
            f"{elem}: avg={r['average_element_intensity']:.3g}, "
            f"clusters={r['num_clusters']}, "
            f"sizes=[{sizes}], intensities=[{intensities}]"
        )
    return "\n".join(text)

def attach_napari_hover(sample, viewer, widget, nuc_layer, mem_layer):
    def tt_hide():
        qt.QToolTip.hideText()

    def tt_show(text):
        qt.QToolTip.showText(qt.QCursor.pos(), text, widget)

    nuclei = sample.nuclei.nuclei_labels
    membrane = sample.nuclei.membrane_labels
    @viewer.mouse_move_callbacks.append
    def _hover(viewer, event):
        if sample is None:
            tt_hide()
            return
        pos = event.position
        if len(pos) < 2:
            print("weird len(pos)")
            tt_hide()
            return
        y, x = map(int, pos[-2:])
        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            tt_hide()
            return

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        if nuc_layer.visible and nuc_label > 0:
            text = build_tooltip_text(
                nuc_label, sample.df_nuclei, sample.element_names)
        elif mem_layer.visible and mem_label > 0:
            text = build_tooltip_text(
                mem_label, sample.df_membrane, sample.element_names)
        else:
            tt_hide()
            return

        # data = layer.data
        # label_val = int(data[y, x])
        # if label_val <= 0:
        #     print("label 0")
        #     tt_hide()
        #     return
        # text = build_tooltip_text(label_val, region_df, sample.element_names)
        if not text:
            tt_hide()
            return
        tt_show(text)

def show_sample_in_napari(sample, viewer, widget):
    if sample is None:
        return
    viewer.layers.clear()

    viewer.add_image(sample.nuclei.raw, name="Nuclei raw", colormap="green")
    viewer.add_image(sample.tissue.raw, name="Tissue raw", visible=False)

    for name, ch in sample.elements.items():
        viewer.add_image(ch.raw, name=f"{name} raw", visible=False)
        if ch.cluster_labels is not None:
            viewer.add_labels(ch.cluster_labels,
                              name=f"{name} clusters", visible=False)

    mem_layer = viewer.add_labels(sample.nuclei.membrane_labels,
                                  name="Membrane labels", visible=False)
    nuc_layer = viewer.add_labels(sample.nuclei.nuclei_labels,
                                  name="Nuclei labels")
    attach_napari_hover(sample, viewer, widget, nuc_layer, mem_layer)
   # attach_region_hover(sample, mem_layer, sample.df_membrane, tooltip)

