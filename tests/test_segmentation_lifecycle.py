"""Regression coverage for worker deletion during modal failure reporting."""

import os
import subprocess
import sys


def test_failed_worker_cleanup_survives_modal_event_loop():
    code = """
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from qtpy import QtCore, QtWidgets

from exhale.analysis import controller as module

app = QtWidgets.QApplication([])
window = QtWidgets.QWidget()
window.clustering_controller = SimpleNamespace(worker=None)
window.project_manager = SimpleNamespace(require_project_directory=lambda _: True)
window.analysisStatus = Mock()
window.analysisBatchStatus = Mock()
window.analysisChNuclei = SimpleNamespace(currentData=lambda: 'P')
window.settings = QtCore.QSettings(QtCore.QSettings.IniFormat,
                                  QtCore.QSettings.UserScope, 'test', 'lifecycle')
window.analysisProcessingTabs = Mock()
window.analysisPostprocessingPage = object()
workers, threads, deleted, errors, messages = [], [], [], [], []
sys.excepthook = lambda *error: errors.append(error)

class Worker(QtCore.QObject):
    progress = QtCore.Signal(str)
    model_progress = QtCore.Signal(str, object, object)
    model_ready = QtCore.Signal()
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, model_error):
        super().__init__()
        self.model_error = model_error

    @QtCore.Slot()
    def run(self):
        self.failed.emit('failure details')

def create_worker(*args, **kwargs):
    worker = Worker('Model unavailable' if not workers else None)
    workers.append(worker)
    return worker

method = SimpleNamespace(unavailable_reason=lambda: None, create_worker=create_worker)
control = SimpleNamespace(
    window=window, worker=None, thread=None, batch=SimpleNamespace(active=False),
    current_sample=lambda: SimpleNamespace(sample_id='sample'),
    current_method_id=lambda: 'cellpose',
    segmentation_parameters=lambda: None,
    _preview=lambda: None,
    _finish_editing=lambda: None,
    element_settings=lambda _: [SimpleNamespace(data=np.ones((2, 2)))],
    _append_status=Mock(), _model_progress=Mock(), _model_ready=Mock(),
    set_busy=Mock(),
)

def report_error(*args):
    messages.append(args)
    assert control.worker is None
    assert control.thread is None
    assert control.set_busy.call_args.args == (False,)
    # Like QMessageBox.exec(), keep dispatching until thread deletion occurs.
    loop = QtCore.QEventLoop()
    threads[-1].destroyed.connect(loop.quit)
    QtCore.QTimer.singleShot(2000, loop.quit)
    loop.exec_()
    assert len(deleted) == len(threads)

window.show_error = report_error
with patch.object(module, 'segmentation_method', return_value=method), \
     patch.object(module.QtWidgets.QMessageBox, 'warning', side_effect=report_error):
    for _ in range(2):
        module.AnalysisController.run(control)
        threads.append(control.thread)
        control.thread.destroyed.connect(lambda: deleted.append(True))
        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if control.worker is None else None)
        timer.start(10)
        QtCore.QTimer.singleShot(3000, loop.quit)
        loop.exec_()
        timer.stop()
        assert control.worker is None
        assert control.thread is None

assert len(messages) == 2
assert len(deleted) == 2
assert not errors, errors
window.close()
"""
    subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
