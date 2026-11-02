#!/usr/bin/env python3
"""Background XRF analysis with Qt progress, completion, and failure signals."""

import contextlib
import logging
import os
import sys
import threading
from copy import copy, deepcopy

import numpy as np
from qtpy import QtCore

from ..data.segmentation import SegmentationParameters


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


@contextlib.contextmanager
def capture_analysis_output(emit):
    """Forward Python/native output and backend logs for either analysis stage."""

    class ProgressStream:
        def __init__(self):
            self.pending = ""
            self.active = True
            self.fallback = sys.stderr

        def write(self, text):
            if not self.active:
                return self.fallback.write(text)
            self.pending += text
            lines = self.pending.split("\n")
            self.pending = lines.pop()
            for line in lines:
                if line:
                    emit(line)

        def flush(self):
            if not self.active:
                return self.fallback.flush()
            if self.pending:
                emit(self.pending)
                self.pending = ""

        def close(self):
            # Backend logging may retain this wrapper; it owns no underlying file.
            pass

    class ProgressHandler(logging.Handler):
        def emit(self, record):
            emit(self.format(record))

    handler = ProgressHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    loggers = [logging.getLogger(name) for name in ("tensorflow", "cellpose")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    stream = ProgressStream()
    try:
        with (
            capture_native_stderr(emit),
            contextlib.redirect_stdout(stream),
            contextlib.redirect_stderr(stream),
        ):
            yield
            stream.flush()
    finally:
        stream.active = False
        for logger, level in zip(loggers, levels, strict=True):
            logger.removeHandler(handler)
            logger.setLevel(level)


class AnalysisTask(QtCore.QObject):
    """Shared progress and cooperative cancellation for independent analysis jobs."""

    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._abort = False

    @QtCore.Slot()
    def run(self):
        """Publish exactly one result or failure, never a cancelled result."""
        try:
            result = self.execute()
        except InterruptedError:
            self.failed.emit("")
        except Exception:
            import traceback

            self.failed.emit(traceback.format_exc())
        else:
            self.finished.emit(result)

    @QtCore.Slot()
    def abort(self):
        self._abort = True

    def report(self, message):
        """Check cancellation at explicit computation boundaries."""
        if self._abort:
            raise InterruptedError("Aborted")
        self.progress.emit(message)

    def execute(self):
        """Compute privately; callers publish and persist only successful output."""
        self.report("Initializing")
        with capture_analysis_output(self.progress.emit):
            result = self.compute()
            self.report("Analysis complete")
        return result

    def compute(self):
        raise NotImplementedError


class AnalysisWorker(AnalysisTask):
    """Acquire model weights and segment one map outside the GUI thread."""

    model_progress = QtCore.Signal(str, object, object)
    model_ready = QtCore.Signal()

    def __init__(
        self,
        image: np.ndarray,
        *,
        method_id="stardist",
        parameters: SegmentationParameters | None = None,
        model_path=None,
        model_directory=None,
    ):
        super().__init__()
        self.image = np.array(image, copy=True)
        self.method_id = method_id
        self.parameters = deepcopy(parameters or SegmentationParameters())
        self.model_path = model_path
        self.model_directory = model_directory
        self.model_error = None

    def compute(self):
        from .model_store import ModelDownloadError, ensure_model, model_for_method
        from .segmentation_backends import run_segmentation

        model = model_for_method(self.method_id)
        if model is not None and self.model_path is None:
            try:
                if self.model_directory is None:
                    raise ModelDownloadError("The model directory is not configured.")
                self.model_path = str(
                    ensure_model(
                        model,
                        self.model_directory,
                        progress=self.model_progress.emit,
                        cancelled=lambda: self._abort,
                    )
                )
            except ModelDownloadError as exc:
                self.model_error = str(exc)
                raise
        self.model_ready.emit()
        return run_segmentation(
            self.method_id,
            self.image,
            self.parameters,
            model_path=self.model_path,
            callback=self.report,
        )


class ClusteringWorker(AnalysisTask):
    """Run the existing element clustering independently of segmentation backends."""

    def __init__(
        self,
        nuclei_es,
        tissue_es,
        element_settings,
        sample_name,
        previous_sample=None,
        retained_elements=(),
        **process_args,
    ):
        super().__init__()
        self.nuclei_es = nuclei_es
        self.tissue_es = tissue_es
        self.element_settings = element_settings
        self.sample_name = sample_name
        self.previous_sample = previous_sample
        self.retained_elements = retained_elements
        self.process_args = process_args

    def xrf_analysis(self):
        """Execute the clustering job for non-Qt callers."""
        return self.execute()

    def compute(self):
        from ..xrf_refcopy.xrf_element_channel import ElementChannel
        from ..xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
        from ..xrf_refcopy.xrf_sample_class import XRFSample

        sample = (
            copy(self.previous_sample)
            if self.previous_sample is not None
            else XRFSample(self.sample_name)
        )
        sample.name = self.sample_name
        if self.previous_sample is None:
            sample.nuclei = None if self.nuclei_es is None else NucleiChannel(self.nuclei_es.data)
            sample.tissue = None if self.tissue_es is None else TissueChannel(self.tissue_es.data)
        sample.elements = {}
        for index, settings in enumerate(self.element_settings):
            previous = self.retained_elements[index] if self.retained_elements else None
            channel = (
                copy(previous)
                if previous is not None
                else ElementChannel(settings.name, settings.data)
            )
            channel.name = settings.name
            sample.elements[settings.name] = channel
        sample.cluster_elements(callback=self.report, **self.process_args)
        if sample.is_segmented and sample.is_clustered and sample.elements:
            self.report("Combining region measurements")
            sample.combine(callback=self.report)
        return sample
