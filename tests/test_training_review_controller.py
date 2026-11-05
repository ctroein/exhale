"""Review applies to accepted whole-mask revisions, never unaccepted edits."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from qtpy import QtWidgets

from exhale.analysis.controller import AnalysisController
from exhale.data.projectdata import SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationHistory
from exhale.data.source_refs import ElementRef


def test_unaccepted_edits_cannot_take_review_from_the_saved_revision():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    checkbox = QtWidgets.QCheckBox()
    history = SegmentationHistory("sample")
    original = history.add_result(
        SegmentationResult(
            "sample",
            "stardist",
            ElementRef("source.h5", "/P"),
            SegmentationParameters(),
            SegmentationOutput(np.array([[0, 42], [0, 0]], dtype=np.uint32), "model", "1"),
        )
    )
    history.set_reviewed(original.candidate_id)
    session = SegmentationEditSession(original)
    labels = session.labels.copy()
    labels[1, 1] = 42
    session.apply_labels(labels)
    control = SimpleNamespace(
        window=SimpleNamespace(analysisReviewedForTraining=checkbox, project_state_manager=Mock()),
        worker=None,
        _edit_session=session,
        current_candidate=lambda: history.active,
        _history=lambda: history,
        refresh_mask_markers=Mock(),
    )
    control._update_review_control = lambda: AnalysisController._update_review_control(control)
    control._update_review_control()
    assert not checkbox.isEnabled() and not checkbox.isChecked()
    AnalysisController._review_mask(control, True)
    assert history.reviewed is original
    control.refresh_mask_markers.assert_not_called()
    control.window.project_state_manager.project_changed.assert_not_called()

    child = history.add_candidate(session.completed_candidate())
    control._edit_session = SegmentationEditSession(child)
    control._edit_session.select(42)
    control._update_review_control()
    assert checkbox.isEnabled() and not checkbox.isChecked()
    AnalysisController._review_mask(control, True)
    assert checkbox.isChecked() and history.reviewed is child
    assert not original.reviewed
    assert control._edit_session.selected_ids == {42}
    np.testing.assert_array_equal(child.result.output.labels, labels)
    control.window.project_state_manager.project_changed.assert_called_once()
    checkbox.deleteLater()
    app.processEvents()
