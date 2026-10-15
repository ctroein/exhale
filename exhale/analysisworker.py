#!/usr/bin/env python3
"""Background XRF analysis with Qt progress, completion, and failure signals."""

import contextlib
import importlib
import os
import sys
import threading

from qtpy import QtCore

from .data.elementsettings import ElementSettings


@contextlib.contextmanager
def capture_native_stderr(emit):
    """Capture writes to file descriptor 2, including native-library logs."""
    try:
        saved_stderr = os.dup(2)
    except OSError:
        yield
        return
    try:
        read_fd, write_fd = os.pipe()
    except OSError:
        os.close(saved_stderr)
        yield
        return

    def drain():
        with os.fdopen(read_fd, "r", errors="replace") as captured:
            for line in captured:
                line = line.rstrip("\r\n")
                if line:
                    emit(line)

    reader = threading.Thread(target=drain, name="analysis-stderr", daemon=True)
    try:
        os.dup2(write_fd, 2)
        os.close(write_fd)
        reader.start()
        yield
    finally:
        sys.__stderr__.flush()
        os.dup2(saved_stderr, 2)
        os.close(saved_stderr)
        reader.join()


class AnalysisWorker(QtCore.QObject):
    """Run one sample analysis outside the GUI thread.

    Progress includes Python output and messages written directly to the native
    stderr descriptor. Abortion is cooperative and is checked at progress
    boundaries.
    """

    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)  # XRFSample
    failed = QtCore.Signal(str)

    def __init__(
        self,
        nuclei_es: ElementSettings,
        tissue_es: ElementSettings,
        element_settings: list,
        sample_name: str,
        **process_args,
    ):
        super().__init__()
        self.nuclei_es = nuclei_es
        self.tissue_es = tissue_es
        self.element_settings = element_settings
        self.sample_name = sample_name
        self.process_args = process_args
        self._abort = False

    @QtCore.Slot()
    def run(self):
        """Run the analysis and emit exactly one completion or failure signal."""

        try:
            sample = self.xrf_analysis()
        except InterruptedError:
            self.failed.emit("")
        except Exception:
            import traceback

            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit(sample)

    @QtCore.Slot()
    def abort(self):
        """Request cooperative cancellation at the next progress boundary."""

        self._abort = True

    def xrf_analysis(self):
        """Build and process an ``XRFSample`` while forwarding library output."""

        # self._abort = False
        def progress_or_abort(msg):
            if self._abort:
                raise InterruptedError("Aborted")
            self.progress.emit(msg)

        # Try to intercept logging
        import logging

        class LogHandler(logging.Handler):
            "Minimal logging handler"

            def __init__(self):
                logging.Handler.__init__(self, logging.DEBUG)
                self.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))

            def emit(self, record):
                try:
                    msg = self.format(record)
                except Exception:
                    msg = record.getMessage()
                progress_or_abort(msg)

        tfLogHandler = LogHandler()
        tf_log = logging.getLogger("tensorflow")
        previous_tf_level = tf_log.level
        tf_log.setLevel(logging.DEBUG)
        tf_log.addHandler(tfLogHandler)

        class EmitStream:
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

            def close(self): ...

        estream = EmitStream()

        try:
            # TensorFlow and StarDist also write directly to the native stderr
            # descriptor while loading the model and starting CUDA.
            with (
                capture_native_stderr(self.progress.emit),
                contextlib.redirect_stdout(estream),
                contextlib.redirect_stderr(estream),
            ):
                from .xrf_refcopy import xrf_utils

                xrf_utils.set_model_basedir(
                    importlib.resources.files("exhale").joinpath("resources/models")
                )
                from .xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
                from .xrf_refcopy.xrf_sample_class import XRFSample

                sample = XRFSample(self.sample_name)
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
        finally:
            tf_log.removeHandler(tfLogHandler)
            tf_log.setLevel(previous_tf_level)
