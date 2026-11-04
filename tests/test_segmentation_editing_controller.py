"""Editing acceptance, rejection and selection-transition data safety."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from exhale.analysis.controller import AnalysisController
from exhale.data.projectdata import ProjectData, Sample, SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.source_refs import ElementRef


def editing_control():
    project = ProjectData()
    project.samples["sample"] = Sample("sample", "Sample")
    result = SegmentationResult(
        "sample",
        "stardist",
        ElementRef("file.h5", "/P"),
        SegmentationParameters(),
        SegmentationOutput(np.full((7, 9), 42, dtype=np.uint32), "model", "1"),
    )
    project.set_segmentation_result(result)
    history = project.segmentation_histories["sample"]
    session = SegmentationEditSession(history.active)
    session.select(42)
    session.edit("remove", [(0, 4), (6, 4)], size=3)
    project.segmentation_edit_sessions["sample"] = session
    control = SimpleNamespace(
        window=SimpleNamespace(project_data=project, project_state_manager=Mock()),
        naparihelper=Mock(),
        _edit_session=session,
        _resolve_disconnections=Mock(return_value=True),
        _refresh_masks=Mock(),
        _update_edit_controls=Mock(),
    )
    return control, history, session


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_explicit_finish_preserves_source_and_either_publishes_or_discards(decision):
    control, history, session = editing_control()
    original = history.active
    assert AnalysisController._finish_editing(control, decision=decision)
    assert control._edit_session is None
    assert not control.window.project_data.segmentation_edit_sessions
    assert np.all(original.result.output.labels == 42)
    if decision == "accept":
        control._resolve_disconnections.assert_called_once()
        assert len(history.candidates) == 2
        assert history.active.edited and history.active.parent_id == original.candidate_id
    else:
        control._resolve_disconnections.assert_not_called()
        assert len(history.candidates) == 1 and history.active is original


def test_cancelled_navigation_and_cancelled_disconnection_retain_draft():
    control, history, session = editing_control()
    with patch("exhale.analysis.controller.QtWidgets.QMessageBox") as box:
        box.return_value.clickedButton.return_value = None
        assert not AnalysisController._finish_editing(control)
    assert control._edit_session is session and len(history.candidates) == 1
    assert control.window.project_data.segmentation_edit_sessions["sample"] is session
    control._resolve_disconnections.return_value = False
    assert not AnalysisController._finish_editing(control, decision="accept")
    assert control._edit_session is session and len(history.candidates) == 1


def test_selection_change_resolves_old_segment_first_and_cancel_keeps_selection():
    control, _history, session = editing_control()
    control._resolve_disconnections.return_value = False
    assert not AnalysisController._select_segment(control, 0, False, position=(2, 4))
    assert session.selected_ids == {42}
    control._resolve_disconnections.assert_called_with({42})
    control.naparihelper.update_selection.assert_not_called()


def test_selection_uses_the_clicked_part_after_a_pending_split_is_resolved():
    control, _history, session = editing_control()

    def resolve(identities):
        assert identities == {42}
        session.resolve_disconnection(42, split=True)
        return True

    control._resolve_disconnections.side_effect = resolve
    assert AnalysisController._select_segment(control, 42, True, position=(2, 7))
    assert session.labels[2, 7] == 1
    assert session.selected_ids == {1, 42}
