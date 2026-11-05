"""Sequential background segmentation with incremental, view-preserving publication."""

from copy import deepcopy
from pathlib import Path

import numpy as np
from qtpy import QtCore, QtWidgets

from ..data.projectdata import SegmentationLayerSettings, SegmentationResult
from ..data.segmentation import SegmentationPostprocessing
from ..model_settings import model_directory
from .analysisworker import AnalysisWorker
from .segmentationio import publish_segmentation


class BatchSegmentationWorker(AnalysisWorker):
    """Reuse inference runtime/model acquisition across jobs, loading one map at a time."""

    sample_started = QtCore.Signal(int, object)
    sample_finished = QtCore.Signal(object, object)
    sample_failed = QtCore.Signal(object, str)

    def __init__(self, jobs, sources, **kwargs):
        super().__init__(np.empty((0, 0)), **kwargs)
        self.jobs = tuple(jobs)
        self.sources = dict(sources)

    def compute(self):
        completed = []
        for index, job in enumerate(self.jobs):
            self.report(f"Segmenting {job.sample_name}")
            self.sample_started.emit(index, job)
            try:
                self.image = self.sources[job.input_ref.source_id].load_array(job.input_ref)
                output = super().compute()
                self.report(f"Completed {job.sample_name}")
                self.sample_finished.emit(job, output)
                completed.append(job.sample_id)
            except InterruptedError:
                raise
            except Exception as exc:
                self.sample_failed.emit(job, str(exc))
                if self.model_error is not None:
                    # Retrying acquisition for every sample cannot fix a shared model failure.
                    break
            finally:
                self.image = np.empty((0, 0))
        return completed


class SegmentationBatchController(QtCore.QObject):
    """Own a transient queue, worker lifetime and publication into the captured project."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.window = owner.window
        self.worker = None
        self.thread = None
        self.active = False
        self.stopping = False
        self._generation = None

    def start(self, jobs, method_id, parameters):
        """Snapshot queue configuration without finishing or replacing working edits."""
        if self.active or not jobs:
            raise ValueError("A batch requires jobs and no running batch")
        self.jobs = tuple(jobs)
        self.method_id = method_id
        self.parameters = deepcopy(parameters)
        self.project = self.window.project_data
        self.project_dir = Path(self.window.project_dir)
        self.completed, self.failures = [], []
        self.active, self.stopping = True, False
        generation = self._generation = object()
        thread = self.thread = QtCore.QThread(self.window)
        worker = self.worker = BatchSegmentationWorker(
            self.jobs,
            self.project.sources,
            method_id=method_id,
            parameters=self.parameters,
            model_directory=model_directory(self.window.settings),
        )
        worker.moveToThread(thread)

        def current(callback):
            def receive(*args):
                if self._generation is generation:
                    callback(*args)

            return receive

        worker.progress.connect(current(self.owner._append_status))
        worker.model_progress.connect(current(self.owner._model_progress))
        worker.model_ready.connect(current(self.owner._model_ready))
        worker.sample_started.connect(current(self._started))
        worker.sample_finished.connect(current(self._publish))
        worker.sample_failed.connect(current(self._failed_sample))
        worker.failed.connect(current(self._failed_batch))
        worker.finished.connect(thread.quit, QtCore.Qt.DirectConnection)
        worker.failed.connect(thread.quit, QtCore.Qt.DirectConnection)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(current(self._finished))
        thread.finished.connect(thread.deleteLater)
        self.owner.set_busy(False, preserve_view=True)
        self.window.analysisBatchStatus.setVisible(True)
        self.window.analysisBatchStatus.setText(f"Starting batch — {len(self.jobs)} samples")
        self.window.analysisProgress.setRange(0, 0)
        thread.start()

    def _started(self, index, job):
        self.owner._model_progress_phase = None
        self.window.analysisBatchStatus.setText(
            f"{job.sample_name} — {index + 1} of {len(self.jobs)}"
        )
        self.window.analysisProgress.setTextVisible(False)
        self.window.analysisProgress.setRange(0, 0)

    def _publish(self, job, output):
        """Save before making a result available; leave the user's active mask alone."""
        sample = self.project.samples.get(job.sample_id)
        if sample is None or job.input_ref not in {c.ref for c in sample.channels.values()}:
            self._failed_sample(job, "The sample or input channel was removed during the batch")
            return
        history = self.project.segmentation_histories.get(job.sample_id)
        previous = None if history is None else history.active
        preview = self.project.segmentation_previews.get(job.sample_id, {}).get(self.method_id)
        presentation = previous.result if previous is not None else preview
        result = SegmentationResult(
            job.sample_id,
            self.method_id,
            job.input_ref,
            deepcopy(self.parameters),
            output,
            layer_settings=deepcopy(presentation.layer_settings)
            if presentation
            else SegmentationLayerSettings(),
            postprocessing=previous.result.postprocessing
            if previous
            else SegmentationPostprocessing(),
            reference_refs=presentation.reference_refs if presentation else (),
        )
        try:
            publish_segmentation(self.project, result, self.project_dir, activate=False)
        except Exception as exc:
            self._failed_sample(job, f"Saving the segmentation failed: {exc}")
            return
        self.completed.append(job.sample_id)
        self.window.project_state_manager.project_changed()
        self.window.segmentationResultsChanged.emit()
        viewed = self.owner.current_sample()
        if viewed is not None and viewed.sample_id == job.sample_id:
            if previous is None and self.owner._edit_session is None:
                self.owner.sample_changed()
            else:
                self.owner._refresh_masks(incremental=True)
        self.owner._append_status(f"Saved segmentation for {job.sample_name}")

    def _failed_sample(self, job, details):
        self.failures.append(f"{job.sample_name}: {details}")
        self.owner._append_status(f"Failed — {self.failures[-1]}")

    def _failed_batch(self, details):
        if details:
            self.failures.append(details)
        else:
            self.stopping = True

    def _finished(self):
        """Re-enable run controls only after the inference thread has actually stopped."""
        self.worker = self.thread = None
        self.active = False
        self._generation = None
        done, total = len(self.completed), len(self.jobs)
        stopped = self.stopping or done + len(self.failures) < total
        text = f"{'Stopped' if stopped else 'Batch complete'} — {done} of {total} completed"
        if self.failures:
            text += f", {len(self.failures)} failed"
        self.window.analysisBatchStatus.setText(text)
        self.owner._append_status(text)
        self.owner.set_busy(False, preserve_view=True)
        if self.failures:
            message = QtWidgets.QMessageBox(self.window)
            message.setIcon(QtWidgets.QMessageBox.Warning)
            message.setWindowTitle("Batch segmentation")
            message.setText(text)
            message.setInformativeText(
                ("Completed masks are available." if self.completed else "No new masks were saved.")
                + " See the details for failures."
            )
            message.setDetailedText("\n\n".join(self.failures))
            message.exec()

    def abort(self):
        """Cancel the current inference cooperatively and discard the remaining queue."""
        if self.active and self.worker is not None:
            self.stopping = True
            self.window.analysisBatchStatus.setText("Stopping batch…")
            self.worker.abort()

    def shutdown(self):
        """Invalidate queued publications before waiting for cancellation or changing projects."""
        self._generation = None
        if self.worker is not None:
            self.worker.abort()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        self.worker = self.thread = None
        self.active = False
