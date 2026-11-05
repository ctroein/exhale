"""Area selection preserves pending edits and adds IDs without toggling them off."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from exhale.analysis.controller import AnalysisController


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
