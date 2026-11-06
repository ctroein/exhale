"""Fitted outlines commit on release as one protected, undoable edit."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from qtpy import QtCore, QtWidgets

from exhale.analysis.boundaryfitting import fit_outline
from exhale.analysis.controller import AnalysisController
from exhale.data.projectdata import SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate
from exhale.data.source_refs import ElementRef
from exhale.main_window_ui import Ui_MainWindow


@pytest.fixture
def control():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(window)
    for name, widget in vars(ui).items():
        setattr(window, name, widget)
    window.analysisDisconnectedParts.addItem("Keep together", "keep")
    y, x = np.mgrid[:65, :65]
    image = ((y - 32) ** 2 + (x - 32) ** 2 <= 100).astype(float)
    labels = np.zeros(image.shape, np.uint32)
    labels[31:34, 39:42] = 42
    candidate = SegmentationCandidate.from_result(
        SegmentationResult(
            "sample",
            "stardist",
            ElementRef("file", "/P"),
            SegmentationParameters(),
            SegmentationOutput(labels, "test", "1"),
        )
    )
    session = SegmentationEditSession(candidate)
    controller = AnalysisController.__new__(AnalysisController)
    QtCore.QObject.__init__(controller, window)
    controller.window = window
    controller._edit_session = session
    controller.naparihelper = SimpleNamespace(cancel_stroke=Mock())
    controller._input_map = Mock(return_value=image)
    controller._update_edit_controls = Mock()
    controller._editing_changed = Mock()
    controller._resolve_disconnections = Mock(return_value=True)
    window.analysisFitOutline.setChecked(True)
    window.analysisOutlineDistance.setValue(4)
    yield controller, session, window, image
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


OUTLINE = [(19, 19), (19, 45), (45, 45), (45, 19)]


def test_outline_has_no_filled_fan_while_drawing(control):
    controller, session, _, _ = control
    before = session.labels.copy()
    for count in range(1, len(OUTLINE) + 1):
        np.testing.assert_array_equal(
            controller._edit_gesture("draw", OUTLINE[:count], preview=True), before
        )
    assert not session.changed


def test_fit_uses_raw_input_distance_and_protection(control):
    controller, session, window, image = control
    before = session.labels.copy()
    revision = session.revision_id
    with patch("exhale.analysis.controller.fit_outline", wraps=fit_outline) as fit:
        preview = controller._edit_gesture("draw", OUTLINE)
    assert fit.call_count == 1
    args, kwargs = fit.call_args
    assert args[0] is image
    assert kwargs["max_distance"] == 4
    np.testing.assert_array_equal(kwargs["protected"], before != 0)
    assert session.changed and session.can_undo and session.revision_id != revision
    assert preview[32, 40] == 42 and (preview == 1).any()
    np.testing.assert_array_equal(session.labels, preview)
    controller._editing_changed.assert_called_once()
    session.undo()
    assert not session.can_undo
    np.testing.assert_array_equal(session.labels, before)


def test_fit_off_commits_directly_without_calling_the_fitter(control):
    controller, session, window, _ = control
    window.analysisFitOutline.setChecked(False)
    with patch("exhale.analysis.controller.fit_outline") as fit:
        controller._edit_gesture("draw", OUTLINE)
    fit.assert_not_called()
    assert session.changed and session.can_undo


@pytest.mark.parametrize("tool", ["outline_add", "outline_remove"])
def test_fitted_outline_preserves_modifier_operation_and_selection(control, tool):
    controller, session, _, _ = control
    session.select(42)
    controller._edit_gesture(tool, OUTLINE)
    assert session.changed and session.can_undo
    assert session.selected_ids <= {42}
    assert set(np.unique(session.labels)) <= {0, 42}


def test_failed_fit_preserves_labels_and_reports_a_handled_error(control):
    controller, session, _, _ = control
    before = session.labels.copy()
    controller._input_map.return_value = None
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        controller._edit_gesture("draw", OUTLINE)
    assert warning.call_count == 1
    assert "unavailable" in warning.call_args.args[2]
    np.testing.assert_array_equal(session.labels, before)
    assert not session.can_undo


def test_cancelled_disconnection_question_does_not_run_fit_or_commit(control):
    controller, session, _, _ = control
    controller._resolve_disconnections.return_value = False
    with patch("exhale.analysis.controller.fit_outline") as fit:
        controller._edit_gesture("draw", OUTLINE)
    fit.assert_not_called()
    assert not session.changed and not session.can_undo
