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
from .constants import CONCENTRATION_UNITS

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
        self.viewer.mouse_drag_callbacks.append(self._click)
        self.info_widget = None

    def set_info_widget(self, widget):
        self.info_widget = widget

    def _point(self, event):
        pos = event.position
        if len(pos) < 2:
            return None
        return tuple(map(int, pos[-2:]))

    def _build_tooltip_text(self,
            label_val: int, region_df, element_names: list[str],
            region_name: str) -> str:
        rows = region_df[region_df["label"] == label_val]
        if rows.empty:
            return ""

        text = [f"{region_name}: {label_val}"]
        for elem in element_names:
            row = rows[rows["element"] == elem]
            if row.empty:
                continue
            r = row.iloc[0]
            # sizes = ", ".join(f"{v:.0f}" for v in r["cluster_sizes"])
            # intensities = ", ".join(f"{v:.3g}" for v in r["cluster_intensities"])
            text.append(
                f"{elem}: avg={r['average_element_intensity']:.3g} ng/mm², "
                f"number of overlapping clusters={r['num_clusters']}"
                # f"sizes=[{sizes}], intensities=[{intensities}]"
            )
        return "\n".join(text)

    @staticmethod
    def _cluster_row(ch, label):
        if ch.cluster_df is None or label <= 0:
            return None
        rows = ch.cluster_df[ch.cluster_df["label"] == label]
        return None if rows.empty else rows.iloc[0]

    def _cluster_tooltip_text(self, y, x):
        lines = []
        for name, ch in self.sample.elements.items():
            if ch.cluster_labels is None:
                continue
            if not (0 <= y < ch.cluster_labels.shape[0] and
                    0 <= x < ch.cluster_labels.shape[1]):
                continue
            label = int(ch.cluster_labels[y, x])
            row = self._cluster_row(ch, label)
            if row is None:
                continue
            lines.append(
                f"{name} ({row['area']:.0f} px, "
                f"avg {row['mean_intensity']:.4g} {CONCENTRATION_UNITS})")
        return "" if not lines else "Clusters:\n" + "\n".join(lines)

    def _tt_hide(self):
        qt.QToolTip.hideText()

    def _tt_show(self, text):
        qt.QToolTip.showText(qt.QCursor.pos(), text, self.qtwidget)

    def _hover(self, obj, event):
        if self.sample is None:
            return self._tt_hide()
        sample = self.sample
        point = self._point(event)
        if point is None:
            return self._tt_hide()
        y, x = point
        nuclei = sample.nuclei.nuclei_labels
        membrane = sample.nuclei.membrane_labels
        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            return self._tt_hide()

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        text = None
        if self.nuc_layer.visible and nuc_label > 0:
            text = self._build_tooltip_text(
                nuc_label, sample.df_nuclei, sample.element_names, "Nucleus")
        elif self.mem_layer.visible and mem_label > 0:
            text = self._build_tooltip_text(
                mem_label, sample.df_membrane, sample.element_names, "Membrane")
        cluster_text = self._cluster_tooltip_text(y, x)
        if text and cluster_text:
            text += "\n\n" + cluster_text
        elif cluster_text:
            text = cluster_text

        if not text:
            return self._tt_hide()
        self._tt_show(text)

    def _click(self, obj, event):
        if event.type != "mouse_press" or event.button != 1:
            return
        if self.sample is None or self.info_widget is None:
            return

        point = self._point(event)
        if point is None:
            return
        y, x = point
        sample = self.sample
        nuclei = sample.nuclei.nuclei_labels
        membrane = sample.nuclei.membrane_labels
        self.info_widget.clear()

        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            return

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        if nuc_label > 0:
            region_name = "Nucleus"
            region_label = nuc_label
            region_labels = nuclei
            region_df = sample.df_nuclei
        elif mem_label > 0:
            region_name = "Membrane"
            region_label = mem_label
            region_labels = membrane
            region_df = sample.df_membrane
        else:
            region_name = "Background"
            region_label = 0
            region_labels = None
            region_df = None

        lines = [
            f"Clicked coordinates: x={x}, y={y}",
            f"{region_name}: {region_label}",
        ]

        if region_labels is not None:
            region_mask = region_labels == region_label
            lines.append(f"{region_name} size: {int(region_mask.sum())} px")
        else:
            region_mask = None

        for elem, ch in sample.elements.items():
            lines.extend(["", elem])

            if 0 <= y < ch.raw.shape[0] and 0 <= x < ch.raw.shape[1]:
                lines.append(
                    f"Point intensity: {ch.raw[y, x]:.4g} "
                    f"{CONCENTRATION_UNITS}")

            if region_df is not None:
                rows = region_df[
                    (region_df["label"] == region_label) &
                    (region_df["element"] == elem)
                ]
                if not rows.empty:
                    r = rows.iloc[0]
                    lines.append(
                        f"Average intensity in {region_name.lower()}: "
                        f"{r['average_element_intensity']:.4g} "
                        f"{CONCENTRATION_UNITS}")

            if region_mask is not None and ch.cluster_labels is not None:
                cluster_ids = sorted(
                    int(v) for v in set(ch.cluster_labels[region_mask])
                    if int(v) > 0)
                if cluster_ids:
                    lines.append("Overlapping element clusters:")
                    for cid in cluster_ids:
                        row = self._cluster_row(ch, cid)
                        if row is None:
                            continue
                        overlap = int(
                            ((ch.cluster_labels == cid) & region_mask).sum())
                        lines.append(
                            f"  {cid}: size {row['area']:.0f} px, "
                            f"overlap {overlap} px, "
                            f"avg {row['mean_intensity']:.4g} "
                            f"{CONCENTRATION_UNITS}")

            if ch.cluster_labels is not None:
                cid = int(ch.cluster_labels[y, x])
                row = self._cluster_row(ch, cid)
                if row is not None:
                    lines.append("Element cluster at point:")
                    lines.append(
                        f"  {cid}: size {row['area']:.0f} px, "
                        f"avg {row['mean_intensity']:.4g} "
                        f"{CONCENTRATION_UNITS}")

        self.info_widget.setPlainText("\n".join(lines))

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

