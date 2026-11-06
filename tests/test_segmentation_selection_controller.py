"""Area selection preserves pending edits and adds IDs without toggling them off."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qtpy import QtWidgets

from exhale.analysis.controller import AnalysisController


@pytest.mark.parametrize("changed, already_active", [(True, False), (True, True), (False, False)])
def test_entering_saved_edits_notifies_once_not_on_refresh(changed, already_active):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tabs = QtWidgets.QTabWidget()
    page = QtWidgets.QWidget()
    tabs.addTab(page, "Edit")
    draft = SimpleNamespace(changed=changed, source=SimpleNamespace(sample_id="sample"))
    control = SimpleNamespace(
        window=SimpleNamespace(
            project_data=SimpleNamespace(segmentation_edit_sessions={"sample": draft}),
            analysisProcessingTabs=tabs,
            analysisEditingPage=page,
        ),
        _edit_session=draft if already_active else None,
        _result_sample_id=None,
        current_sample=lambda: SimpleNamespace(sample_id="sample"),
        current_candidate=lambda: SimpleNamespace(result=object()),
        update_channels=Mock(),
        _refresh_reference_choices=Mock(),
        _refresh_masks=Mock(),
        _load_method_parameters=Mock(),
        _notify_resumed_edits=Mock(),
    )

    def resume(*args, **kwargs):
        control._edit_session = draft

    control.show_result = Mock(side_effect=resume)
    AnalysisController.sample_changed(control)
    AnalysisController.sample_changed(control)
    assert control._notify_resumed_edits.call_count == int(changed and not already_active)
    tabs.close()
    app.processEvents()


@pytest.mark.parametrize("additive, expected", [(False, {7, 42}), (True, {7, 42, 99})])
def test_area_selection_resolves_then_reads_current_ids(additive, expected):
    session = SimpleNamespace(
        selected_ids={42, 99},
        labels=object(),
        rectangle_ids=Mock(side_effect=[{7}, {7, 42}]),
    )
    control = SimpleNamespace(
        _edit_session=session,
        _resolve_disconnections=Mock(return_value=True),
        naparihelper=Mock(),
        _update_edit_controls=Mock(),
    )
    corners = ((0, 0), (2, 2))
    AnalysisController._select_rectangle(control, corners, additive)
    control._resolve_disconnections.assert_called_once_with({42, 99})
    assert session.rectangle_ids.call_count == 2
    assert session.selected_ids == expected
    control.naparihelper.update_selection.assert_called_once()
    control._update_edit_controls.assert_called_once()


def test_cancelling_pending_disconnections_keeps_area_selection_unchanged():
    session = SimpleNamespace(selected_ids={99}, rectangle_ids=Mock(return_value={42}))
    control = SimpleNamespace(
        _edit_session=session,
        _resolve_disconnections=Mock(return_value=False),
        naparihelper=Mock(),
        _update_edit_controls=Mock(),
    )
    AnalysisController._select_rectangle(control, ((0, 0), (2, 2)), False)
    assert session.selected_ids == {99}
    control.naparihelper.update_selection.assert_not_called()
    control._update_edit_controls.assert_not_called()
