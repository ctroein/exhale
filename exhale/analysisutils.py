#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar 27 00:34:39 2026

@author: carl
"""

# import os
# import numpy as np
import importlib
from .elementsettings import ElementSettings
from silx.gui import qt
from skimage import morphology
import contextlib
import sys

import napari

class AnalysisWorker(qt.QObject):
    progress = qt.Signal(str)
    finished = qt.Signal(object)   # XRFSample
    failed = qt.Signal(str)

    def __init__(self, nuclei_es: ElementSettings, tissue_es: ElementSettings,
                 element_settings: list, **process_args):
        super().__init__()
        print("AW init")
        self.nuclei_es = nuclei_es
        self.tissue_es = tissue_es
        self.element_settings = element_settings
        self.process_args = process_args
        self._abort = False

    @qt.Slot()
    def run(self):
        print("AW run")
        try:
            sample = self.xrf_analysis()
        except InterruptedError:
            self.failed.emit("")
        except Exception:
            import traceback
            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit(sample)

    @qt.Slot()
    def abort(self):
        print("AW abort")
        self._abort = True

    # def init_libs(self):
    #     "Defers loading of TF, stardist and such"
    #     # Uncomment in case we need to load from . instead of a specified path
    #     # _cwd = os.getcwd()
    #     # import exhale.resources
    #     # os.chdir(next(iter(exhale.resources.__path__)))
    #     from .xrf_refcopy import xrf_utils
    #     xrf_utils.set_model_basedir(
    #         importlib.resources.files("exhale").joinpath("resources"))
    #     # os.chdir(_cwd)
    #     # assert xrf_utils.model

    def xrf_analysis(self):
        # init_libs()

        self._abort = False
        def progress_or_abort(msg):
            if self._abort:
                raise InterruptedError("Aborted")
            self.progress.emit(msg)

        class EmitStream():
            "Stream that collects entire lines and emits them as progress"
            def __init__(self):
                self._s = []
            def write(self, text):
                self._s.append(text)
                if "\n" in text:
                    self.flush()
            def flush(self):
                s = "".join(self._s)
                for t in s.split("\n"):
                    if t:
                        progress_or_abort(t)
                self._s = []
            def close(self):
                ...
        estream = EmitStream()

        # Late loading of TF and stardist
        with (contextlib.redirect_stdout(estream),
            contextlib.redirect_stderr(estream)):
            from .xrf_refcopy import xrf_utils
            xrf_utils.set_model_basedir(
                importlib.resources.files("exhale").joinpath("resources"))
            from .xrf_refcopy.xrf_sample_class import XRFSample
            from .xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel

        sample = XRFSample("Default_sample")
        sample.nuclei = NucleiChannel(self.nuclei_es.data)
        sample.tissue = TissueChannel(self.tissue_es.data)
        for es in self.element_settings:
            sample.add_element(es.name, es.data)

        progress_or_abort("Preparing to process")
        sample.process(callback=progress_or_abort, **self.process_args)
        progress_or_abort("Processed; combining")
        sample.combine(callback=progress_or_abort)
        progress_or_abort("Analysis complete")
        return sample


class NapariHelper():
    "All Napari-related things that aren't strongly tied to our Qt widgets"
    def __init__(self, theme='light'):
        viewer = napari.viewer.Viewer(show=False)
        viewer.theme = theme
        self.viewer = viewer
        self.qtwidget = napari.qt.QtViewer(viewer)
        self.sample = None
        self.nuc_layer = None
        self.mem_layer = None
        viewer.mouse_move_callbacks.append(self._hover)

    def __del__(self):
        print("CLOSE napari viewer")
        self.viewer.close()

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

