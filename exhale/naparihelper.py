#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 13 01:02:40 2026

@author: carl
"""

from skimage import morphology
from silx.gui import qt
import napari
from napari.components import ViewerModel

class NapariHelper():
    "All Napari-related things that aren't strongly tied to our Qt widgets"
    def __init__(self, theme="light"):
        viewer_model = ViewerModel()
        viewer_model.theme = theme
        self.viewer = viewer_model
        self.qtwidget = napari.qt.QtViewer(viewer_model)
        self.sample = None
        self.nuc_layer = None
        self.mem_layer = None
        self.viewer.mouse_move_callbacks.append(self._hover)

    def _build_tooltip_text(self,
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

    def _tt_hide(self):
        qt.QToolTip.hideText()

    def _tt_show(self, text):
        qt.QToolTip.showText(qt.QCursor.pos(), text, self.qtwidget)

    def _hover(self, obj, event):
        if self.sample is None:
            return self._tt_hide()
        sample = self.sample
        pos = event.position
        if len(pos) < 2:
            return self._tt_hide()
        y, x = map(int, pos[-2:])
        nuclei = sample.nuclei.nuclei_labels
        membrane = sample.nuclei.membrane_labels
        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            return self._tt_hide()

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        text = None
        if self.nuc_layer.visible and nuc_label > 0:
            text = self._build_tooltip_text(
                nuc_label, sample.df_nuclei, sample.element_names)
        elif self.mem_layer.visible and mem_label > 0:
            text = self._build_tooltip_text(
                mem_label, sample.df_membrane, sample.element_names)
        if not text:
            return self._tt_hide()
        self._tt_show(text)

    def set_sample(self, sample):
        "Set/update the XRFSample, replacing layers"
        self.sample = sample
        if sample is None:
            return
        viewer = self.viewer
        viewer.layers.clear()

        viewer.add_image(sample.tissue.raw, name="Tissue raw", visible=False)
        viewer.add_image(sample.nuclei.raw, name="Nuclei raw", colormap="green")

        for name, ch in sample.elements.items():
            viewer.add_image(ch.raw, name=f"{name} raw", visible=False)
            if ch.cluster_labels is not None:
                viewer.add_labels(ch.cluster_labels,
                                  name=f"{name} clusters", visible=False)

        self.mem_layer = viewer.add_labels(sample.nuclei.membrane_labels,
                                      name="Membrane labels", visible=False)
        self.nuc_layer = viewer.add_labels(morphology.erosion(
            sample.nuclei.nuclei_labels), name="Nuclei labels", opacity=.6)
        # attach_napari_hover(sample, viewer, widget, nuc_layer, mem_layer)

