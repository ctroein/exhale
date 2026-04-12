#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar 27 00:34:39 2026

@author: carl
"""

import importlib
from .elementsettings import ElementSettings
from silx.gui import qt
import contextlib


class AnalysisWorker(qt.QObject):
    progress = qt.Signal(str)
    finished = qt.Signal(object)   # XRFSample
    failed = qt.Signal(str)

    def __init__(self, nuclei_es: ElementSettings, tissue_es: ElementSettings,
                 element_settings: list, **process_args):
        super().__init__()
        print("AW init", self)
        self.nuclei_es = nuclei_es
        self.tissue_es = tissue_es
        self.element_settings = element_settings
        self.process_args = process_args
        self._abort = False

    @qt.Slot()
    def run(self):
        print("AW run", self)
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
        print("AW abort", self)
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

        # self._abort = False
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

