"""Controller for segmentation inputs, execution, display, and export."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from time import strftime

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets
from tifffile import imwrite

from .. import appearance, icons
from ..data.constants import DISPLAY_UNITS
from ..data.projectdata import (
    SegmentationLayerSettings,
    SegmentationParameters,
    SegmentationPreview,
    SegmentationResult,
)
from ..data.segmentation import SegmentationPostprocessing
from ..data.segmentationediting import SegmentationEditSession
from ..data.source_refs import SourceUnavailableError
from ..model_settings import model_directory
from ..project.projectmanager import EXPORT_DIRECTORY_SETTING
from .segmentation_options_dialog import SegmentationOptionsDialog
from .segmentationio import publish_segmentation
from .segmentationmethods import SEGMENTATION_METHODS, segmentation_method

LOAD_NAPARI_EARLY = True


def _scale_font(widget: QtWidgets.QWidget, scale: float) -> None:
    font = widget.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    widget.setFont(font)


class AnalysisController(QtCore.QObject):
    """Own the Segmentation tab's state and behavior."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.naparihelper = None
        self.worker = None
        self.thread = None
        self._result_sample_id = None
        self._result_candidate_id = None
        self._display_result = None
        self._edit_session = None
        self._edit_tool = "select"
        self._edit_shortcuts = []
        self._viewer_canvas = None
        window.napariWidget.installEventFilter(self)
        for method in SEGMENTATION_METHODS:
            window.analysisPipelineComboBox.addItem(method.name, method.method_id)
            reason = method.unavailable_reason()
            if reason is not None:
                item = window.analysisPipelineComboBox.model().item(
                    window.analysisPipelineComboBox.count() - 1
                )
                item.setEnabled(False)
                item.setToolTip(reason)

        available_index = next(
            (
                index
                for index, method in enumerate(SEGMENTATION_METHODS)
                if method.unavailable_reason() is None
            ),
            -1,
        )
        window.analysisPipelineComboBox.setCurrentIndex(available_index)

        self.settings_dialog = SegmentationOptionsDialog(window)
        for spinbox in (window.analysisExpansion, window.analysisMinimumArea):
            option = QtWidgets.QStyleOptionSpinBox()
            option.initFrom(spinbox)
            option.frame = spinbox.hasFrame()
            metrics = spinbox.fontMetrics()
            content = QtCore.QSize(
                metrics.horizontalAdvance("-000000" + spinbox.suffix()), metrics.height()
            )
            spinbox.setMinimumWidth(
                spinbox.style()
                .sizeFromContents(QtWidgets.QStyle.CT_SpinBox, option, content, spinbox)
                .width()
            )
        window.analysisMaskCombo.currentIndexChanged.connect(self._mask_changed)
        window.analysisMaskCombo.lineEdit().editingFinished.connect(self._rename_mask)
        window.analysisKeepMask.toggled.connect(self._keep_mask)
        window.analysisAddComparison.clicked.connect(self._add_comparison)
        window.analysisComparisonCombo.currentIndexChanged.connect(self._update_comparison_controls)
        window.analysisProcessingTabs.currentChanged.connect(self._processing_tab_changed)
        self._tool_buttons = {
            "select": window.analysisToolSelect,
            "draw": window.analysisToolOutline,
            "add": window.analysisToolBrushDraw,
            "remove": window.analysisToolBrushErase,
        }
        self._tool_group = QtWidgets.QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for key, button in self._tool_buttons.items():
            self._tool_group.addButton(button)
            button.clicked.connect(lambda _checked=False, key=key: self._choose_edit_tool(key))
        window.analysisAcceptEdits.clicked.connect(lambda: self._complete_editing("accept"))
        window.analysisRejectEdits.clicked.connect(lambda: self._complete_editing("reject"))
        for text, key in (
            ("Keep together", "keep"),
            ("Split into segments", "split"),
            ("Ask", "ask"),
        ):
            window.analysisDisconnectedParts.addItem(text, key)
        window.analysisDisconnectedParts.setCurrentIndex(2)
        window.analysisDeleteSegment.clicked.connect(self._delete_segments)
        window.analysisBrushSize.valueChanged.connect(self._brush_size_changed)
        window.analysisUndo.clicked.connect(self._undo_edit)
        window.analysisRedo.clicked.connect(self._redo_edit)
        window.analysisOptions.clicked.connect(self._show_method_options)
        window.analysisMinimumArea.valueChanged.connect(self._postprocessing_changed)
        window.analysisExpansion.valueChanged.connect(self._postprocessing_changed)
        window.analysisShowOverview.clicked.connect(self._show_overview)
        window.analysisAddReference.clicked.connect(self._add_reference)
        window.analysisLayerList.removeRequested.connect(self._remove_reference)
        window.analysisLayerList.removeComparisonRequested.connect(self._remove_comparison)
        self._area_plot = pg.PlotWidget()
        self._area_plot.setBackground(None)
        self._area_plot.setLabel("bottom", "Segment area", units="px")
        self._area_plot.setLabel("left", "Segments")
        self._area_plot.setMouseEnabled(x=False, y=False)
        self._area_plot.setMenuEnabled(False)
        self._area_plot.getPlotItem().hideButtons()
        plot_layout = QtWidgets.QVBoxLayout(window.analysisAreaPlotContainer)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self._area_plot)
        window.appearance.changed.connect(self._reload_plot_appearance)
        self._reload_plot_appearance()
        window.analysisPostprocessing.setEnabled(False)
        self._update_edit_controls()

    def current_method_id(self) -> str | None:
        return self.window.analysisPipelineComboBox.currentData()

    def _history(self):
        sample = self.current_sample()
        return self.window.project_data.segmentation_histories.get(
            None if sample is None else sample.sample_id
        )

    def current_candidate(self):
        history = self._history()
        return None if history is None else history.active

    @staticmethod
    def _mask_name(candidate):
        if candidate.name and (
            candidate.name_is_custom or candidate.name != candidate.result.method_id
        ):
            return candidate.name
        method = next(
            (m.name for m in SEGMENTATION_METHODS if m.method_id == candidate.result.method_id),
            candidate.result.method_id,
        )
        try:
            stamp = (
                datetime.fromisoformat(candidate.created_at)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            stamp = candidate.created_at
        return f"{'Edited ' if candidate.edited else ''}{method} {stamp}"

    def _refresh_masks(self, *, rebuild=True):
        """Keep candidate order stable while restoring the sample's active identity."""
        window = self.window
        history = self._history()
        selector = window.analysisMaskCombo
        if rebuild:
            with QtCore.QSignalBlocker(selector):
                selector.clear()
                if history is not None:
                    for candidate in history.candidates.values():
                        selector.addItem(self._mask_name(candidate), candidate.candidate_id)
                    selector.setCurrentIndex(selector.findData(history.active_id))
        candidate = self.current_candidate()
        for button, checked in (
            (window.analysisKeepMask, candidate is not None and candidate.keep),
        ):
            with QtCore.QSignalBlocker(button):
                button.setChecked(checked)
            button.setEnabled(candidate is not None and self.worker is None)
        selector.setEnabled(candidate is not None and self.worker is None)
        self._refresh_comparison_choices()

    def _mask_changed(self):
        history = self._history()
        key = self.window.analysisMaskCombo.currentData()
        if history is None or key not in history.candidates:
            return
        changed = history.active_id != key
        if not self._finish_editing(next_mask=key):
            self._refresh_masks()
            return
        history.activate(key)
        self._refresh_masks(rebuild=False)
        if self.naparihelper is not None:
            self.show_result(history.active.result, fit=False)
        if changed:
            self.window.project_state_manager.project_changed()

    def _editing_mode(self):
        return self.window.analysisProcessingTabs.currentWidget() is self.window.analysisEditingPage

    def _start_editing(self):
        """Resume a recovered draft or create an unchanged, unsaved working session."""
        candidate = self.current_candidate()
        if candidate is None:
            return
        sessions = self.window.project_data.segmentation_edit_sessions
        session = sessions.get(candidate.sample_id)
        if session is None or session.source.candidate_id != candidate.candidate_id:
            session = SegmentationEditSession(candidate)
            sessions[candidate.sample_id] = session
        self._edit_session = session

    def _finish_editing(self, *, next_mask=None, decision=None):
        """Publish changed working labels when leaving their editing context."""
        session = self._edit_session
        if session is None:
            return True
        if self.naparihelper is not None:
            self.naparihelper.cancel_stroke()
        project = self.window.project_data
        sample_id = session.source.sample_id
        if project.segmentation_edit_sessions.get(sample_id) is not session:
            self._edit_session = None
            return True
        if decision is None and session.changed:
            dialog = QtWidgets.QMessageBox(self.window)
            dialog.setWindowTitle("Unfinished mask changes")
            dialog.setText("Accept or reject the changes to this mask?")
            accept = dialog.addButton("Accept", QtWidgets.QMessageBox.AcceptRole)
            reject = dialog.addButton("Reject", QtWidgets.QMessageBox.DestructiveRole)
            dialog.addButton(QtWidgets.QMessageBox.Cancel)
            dialog.exec()
            button = dialog.clickedButton()
            if button not in (accept, reject):
                return False
            decision = "accept" if button is accept else "reject"
        if decision != "reject" and not self._resolve_disconnections():
            return False
        self._edit_session = None
        project.segmentation_edit_sessions.pop(sample_id)
        history = project.segmentation_histories.get(sample_id)
        candidate = None if decision == "reject" else session.completed_candidate()
        if history is not None and candidate is not None:
            history.add_candidate(candidate, active_id=next_mask)
            self.window.project_state_manager.project_changed()
            self._refresh_masks()
        elif session.changed:
            self.window.project_state_manager.project_changed()
        return True

    def _complete_editing(self, decision):
        """Accept or discard changes while retaining the current editing page."""
        if not self._finish_editing(decision=decision):
            return
        candidate = self.current_candidate()
        if candidate is not None and self.naparihelper is not None:
            self.show_result(candidate.result, fit=False)
        self._update_edit_controls()

    def _resolve_disconnections(self, identities=None):
        """Ask about affected instances while their working outlines remain visible."""
        session = self._edit_session
        pending = (
            session.pending_disconnections
            if identities is None
            else session.pending_disconnections & set(identities)
        )
        for identity in sorted(pending):
            count = session.part_count(identity)
            if count <= 1:
                session.pending_disconnections.discard(identity)
                continue
            selection = session.selected_ids.copy()
            session.selected_ids = {identity}
            if self.naparihelper is not None:
                self.naparihelper.nuc_layer.data = session.labels
                self.naparihelper.update_selection()
            dialog = QtWidgets.QMessageBox(self.window)
            dialog.setWindowTitle("Disconnected segment")
            dialog.setText(f"Segment {identity} now has {count} disconnected parts.")
            keep = dialog.addButton("Keep together", QtWidgets.QMessageBox.AcceptRole)
            split = dialog.addButton("Split into segments", QtWidgets.QMessageBox.AcceptRole)
            dialog.addButton(QtWidgets.QMessageBox.Cancel)
            dialog.exec()
            button = dialog.clickedButton()
            session.selected_ids = selection
            if button not in (keep, split):
                if self.naparihelper is not None:
                    self.naparihelper.update_selection()
                return False
            session.resolve_disconnection(identity, split=button is split)
            self.window.project_state_manager.project_changed()
        return True

    def _processing_tab_changed(self):
        if self._editing_mode():
            self._start_editing()
        else:
            if not self._finish_editing():
                with QtCore.QSignalBlocker(self.window.analysisProcessingTabs):
                    self.window.analysisProcessingTabs.setCurrentWidget(
                        self.window.analysisEditingPage
                    )
                return
        candidate = self.current_candidate()
        if candidate is not None and self.naparihelper is not None:
            self.show_result(candidate.result, fit=False)
        self._update_edit_controls()

    def _select_segment(self, identity, toggle, *, position=None):
        session = self._edit_session
        if session is None:
            return False
        selection = session.selected_ids.copy()
        changes_selection = identity not in selection or toggle or identity == 0
        if changes_selection and not self._resolve_disconnections(selection):
            return False
        if position is not None:
            identity = int(session.labels[position])
        session.select(identity, toggle=toggle)
        self.naparihelper.nuc_layer.data = session.labels
        self.naparihelper.update_selection()
        self._update_edit_controls()
        return True

    def _choose_edit_tool(self, tool):
        self._edit_tool = tool
        self._tool_buttons[tool].setChecked(True)
        self._edit_tool_changed()

    def _brush_size_changed(self):
        if self.naparihelper is not None:
            self.naparihelper.set_brush_size(self.window.analysisBrushSize.value())

    def _edit_tool_changed(self):
        if self.naparihelper is not None:
            self.naparihelper.cancel_stroke()
            self.naparihelper.set_edit_tool(self._edit_tool if self._editing_mode() else "select")
        self.window.analysisBrushSize.setEnabled(self._edit_tool in ("add", "remove"))

    def _edit_gesture(self, tool, points, *, preview=False):
        session = self._edit_session
        if session is None:
            return None
        args = dict(
            size=self.window.analysisBrushSize.value(),
            protect=self.window.analysisProtectSegments.isChecked(),
        )
        try:
            if preview:
                return session.preview(tool, points, **args)
            if tool == "draw" and not self._resolve_disconnections(session.selected_ids):
                return session.labels
            if session.edit(
                tool,
                points,
                **args,
                disconnected=self.window.analysisDisconnectedParts.currentData(),
            ):
                self._editing_changed()
        except ValueError as exc:
            if not preview:
                QtWidgets.QMessageBox.warning(self.window, "Cannot edit segment", str(exc))
        return session.labels

    def _delete_segments(self):
        if self._edit_session is not None and self._edit_session.delete_selected():
            self._editing_changed()

    def _update_edit_controls(self):
        session = self._edit_session
        enabled = self.worker is None
        self.window.analysisUndo.setEnabled(enabled and session is not None and session.can_undo)
        self.window.analysisRedo.setEnabled(enabled and session is not None and session.can_redo)
        self.window.analysisDeleteSegment.setEnabled(
            enabled and session is not None and bool(session.selected_ids)
        )
        self.window.analysisProcessingTabs.setEnabled(
            enabled and self.current_candidate() is not None
        )
        editing = enabled and session is not None and self._editing_mode()
        self.window.analysisAcceptEdits.setEnabled(editing)
        self.window.analysisRejectEdits.setEnabled(editing)
        for shortcut in self._edit_shortcuts:
            shortcut.setEnabled(editing)

    def _editing_changed(self):
        """Refresh the working mask and schedule ordinary save/autosave tracking."""
        if self._edit_session is not None:
            self.show_result(self._edit_session.source.result, fit=False)
            self.window.project_state_manager.project_changed()

    def _undo_edit(self):
        if self.naparihelper is not None:
            self.naparihelper.cancel_stroke()
        if self._edit_session is not None and self._edit_session.can_undo:
            self._edit_session.undo()
            self._editing_changed()

    def _redo_edit(self):
        if self.naparihelper is not None:
            self.naparihelper.cancel_stroke()
        if self._edit_session is not None and self._edit_session.can_redo:
            self._edit_session.redo()
            self._editing_changed()

    def _rename_mask(self):
        candidate = self.current_candidate()
        name = self.window.analysisMaskCombo.currentText().strip()
        if not name:
            self._refresh_masks()
            return
        if candidate is not None and name and name != self._mask_name(candidate):
            candidate.name = name
            candidate.name_is_custom = True
            selector = self.window.analysisMaskCombo
            selector.setItemText(selector.currentIndex(), name)
            self.window.project_state_manager.project_changed()

    def _keep_mask(self, keep):
        candidate = self.current_candidate()
        if candidate is not None:
            candidate.keep = keep
            self.window.project_state_manager.project_changed()

    def _refresh_comparison_choices(self):
        """List other saved masks, including comparisons restored with the project."""
        selector = self.window.analysisComparisonCombo
        previous = selector.currentData()
        history = self._history()
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            if history is not None:
                for candidate in history.candidates.values():
                    if candidate.candidate_id != history.active_id:
                        selector.addItem(self._mask_name(candidate), candidate.candidate_id)
            index = selector.findData(previous)
            if index >= 0:
                selector.setCurrentIndex(index)
        selector.setEnabled(selector.count() > 0 and self.worker is None)
        self._update_comparison_controls()

    def _update_comparison_controls(self):
        history = self._history()
        key = self.window.analysisComparisonCombo.currentData()
        candidate = None if history is None else history.candidates.get(key)
        self.window.analysisAddComparison.setEnabled(
            self.worker is None and candidate is not None and not candidate.compare
        )

    def _add_comparison(self):
        history = self._history()
        key = self.window.analysisComparisonCombo.currentData()
        if history is None or key not in history.candidates or key == history.active_id:
            return
        if not history.candidates[key].compare:
            self._set_comparison(history.candidates[key], True)

    def _remove_comparison(self, candidate_id):
        history = self._history()
        if history is not None and candidate_id in history.candidates:
            self._set_comparison(history.candidates[candidate_id], False)

    def _set_comparison(self, candidate, compare):
        """Change a comparison layer without changing the active mask."""
        self._layer_settings_changed()
        candidate.compare = compare
        if compare and candidate.comparison_presentation is not None:
            candidate.comparison_presentation = replace(
                candidate.comparison_presentation, visible=True
            )
        active = self.current_candidate()
        if self.naparihelper is not None and active is not None:
            self.show_result(active.result, fit=False)
        self._refresh_comparison_choices()
        self.window.project_state_manager.project_changed()

    def _comparisons(self):
        history = self._history()
        return (
            ()
            if history is None
            else tuple(
                (candidate, self._mask_name(candidate))
                for candidate in history.candidates.values()
                if candidate.compare and candidate.candidate_id != history.active_id
            )
        )

    def _load_method_parameters(self):
        """Restore this method's last run options without selecting its mask."""
        history = self._history()
        candidate = None if history is None else history.latest_for_method(self.current_method_id())
        if candidate is not None:
            parameters = next(
                run.parameters
                for run in reversed(candidate.provenance)
                if run.method_id == self.current_method_id()
            )
            self._set_segmentation_parameters(parameters)

    def _show_method_options(self) -> None:
        method_id = self.current_method_id()
        if method_id is not None and segmentation_method(method_id).has_options:
            self.settings_dialog.set_method(method_id)
            self.settings_dialog.show()
            self.settings_dialog.raise_()

    def eventFilter(self, watched, event):
        if (
            watched is self._viewer_canvas
            and event.type() == QtCore.QEvent.KeyPress
            and event.key() == QtCore.Qt.Key_Escape
            and self.naparihelper is not None
        ):
            self.naparihelper.cancel_stroke()
            return True
        if watched is self.window.napariWidget and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
        ):
            self._place_view_buttons()
        return super().eventFilter(watched, event)

    def _place_view_buttons(self) -> None:
        """Keep the view controls inside the Napari area's upper-right corner."""
        margin = 6
        spacing = 4
        right = self.window.napariWidget.width() - margin
        for button in (self.window.analysisFit, self.window.analysisSaveView):
            button.adjustSize()
            right -= button.width()
            button.move(right, margin)
            button.raise_()
            right -= spacing

    def setup(self, *, initialize_view: bool = LOAD_NAPARI_EARLY) -> None:
        """Connect the tab and optionally initialize Napari eagerly."""

        def tab_check():
            if self.window.tabWidget.currentWidget() != self.window.analysisTab:
                if self._edit_session is not None:
                    destination = self.window.tabWidget.currentWidget()
                    with QtCore.QSignalBlocker(self.window.tabWidget):
                        self.window.tabWidget.setCurrentWidget(self.window.analysisTab)
                    if not self._finish_editing():
                        return
                    with QtCore.QSignalBlocker(self.window.analysisProcessingTabs):
                        self.window.analysisProcessingTabs.setCurrentWidget(
                            self.window.analysisPostprocessingPage
                        )
                    candidate = self.current_candidate()
                    if candidate is not None:
                        self.show_result(candidate.result, fit=False)
                    self.window.tabWidget.setCurrentWidget(destination)
                return
            if self.naparihelper is None:
                self.initialize_view()
            self._select_default_nuclei_channel()
            self.refresh_result_view()
            self._refresh_comparison_choices()
            self._update_overview(show=False)
            if self._display_result is not None:
                self.naparihelper.update_reference_maps(
                    self._reference_maps(self._display_result.reference_refs)
                )

        self.window.tabWidget.currentChanged.connect(tab_check)
        if initialize_view:
            self.initialize_view()

    def shutdown(self) -> None:
        """Close auxiliary UI and stop an active worker before application exit."""
        self.settings_dialog.close()
        if self.worker is not None:
            self.worker.abort()
            self.thread.wait()

    def fit_view(self, *_unused) -> None:
        """Fit the segmentation layers to the full available canvas."""
        if self.naparihelper is not None:
            self.naparihelper.viewer.reset_view(margin=0)

    def initialize_view(self) -> None:
        """Create the embedded Napari viewer and connect analysis controls."""
        from .segmentation_viewer import SegmentationViewer

        window = self.window
        self.naparihelper = SegmentationViewer(
            "dark" if appearance.is_dark() else "light",
            self.window.project_data.abundance_units,
        )
        self._brush_size_changed()
        window.analysisLayerList.set_helper(self.naparihelper)
        window.analysisLayerList.presentationChanged.connect(self._layer_settings_changed)
        self.naparihelper.set_info_widget(window.analysisInfo)
        self.naparihelper.inspection_callback = lambda: window.analysisInfoStack.setCurrentWidget(
            window.analysisDetails
        )
        self.naparihelper.selection_callback = self._select_segment
        self.naparihelper.edit_callback = self._edit_gesture

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.naparihelper.qtwidget, 1)
        window.napariWidget.setLayout(layout)
        self._viewer_canvas = self.naparihelper.qtwidget.canvas.native
        self._viewer_canvas.installEventFilter(self)
        for key, slot in (
            (QtGui.QKeySequence.Undo, self._undo_edit),
            (QtGui.QKeySequence.Redo, self._redo_edit),
        ):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(key), self._viewer_canvas)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            button = window.analysisUndo if key == QtGui.QKeySequence.Undo else window.analysisRedo
            binding = shortcut.key().toString(QtGui.QKeySequence.NativeText)
            button.setToolTip(f"{button.toolTip()} ({binding})")
        for key, button in (
            ("S", window.analysisToolSelect),
            ("O", window.analysisToolOutline),
            ("B", window.analysisToolBrushDraw),
            ("E", window.analysisToolBrushErase),
            ("Delete", window.analysisDeleteSegment),
        ):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(key), self._viewer_canvas)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(button.click)
            self._edit_shortcuts.append(shortcut)
        self._place_view_buttons()

        _scale_font(window.analysisStatus, 0.8)
        window.analysisSampleComboBox.currentIndexChanged.connect(self.sample_changed)
        window.analysisPipelineComboBox.currentIndexChanged.connect(self.method_changed)
        window.channelsChanged.connect(self.update_channels)
        self.update_channels()
        window.analysisRun.pressed.connect(self.run)
        window.analysisAbort.pressed.connect(self.abort)
        window.analysisExport.clicked.connect(self.export_results)
        window.analysisSaveView.clicked.connect(self.save_current_view)
        window.analysisFit.clicked.connect(self.fit_view)
        window.analysisChNuclei.currentIndexChanged.connect(self._input_changed)
        self.set_busy(False)

    def abort(self) -> None:
        if self.worker is not None:
            self.worker.abort()

    def current_sample(self):
        """Return the sample selected on the Segmentation tab."""
        sample_id = self.window.analysisSampleComboBox.currentData()
        return self.window.project_data.samples.get(sample_id)

    def refresh_samples(self, entries, fallback_sample_id=None) -> None:
        """Refresh the independently selected analysis sample."""
        selector = self.window.analysisSampleComboBox
        selected = selector.currentData()
        if selected not in self.window.project_data.samples:
            selected = fallback_sample_id
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            for label, sample_id in entries:
                selector.addItem(label, sample_id)
            index = selector.findData(selected)
            selector.setCurrentIndex(index if index >= 0 else (0 if entries else -1))
        if self.naparihelper is not None:
            self.sample_changed()

    def sample_changed(self) -> None:
        """Update segmentation inputs for the independently selected sample."""
        sample = self.current_sample()
        sample_id = None if sample is None else sample.sample_id
        if self._edit_session is not None and self._edit_session.source.sample_id != sample_id:
            previous_sample = self._edit_session.source.sample_id
            if not self._finish_editing():
                selector = self.window.analysisSampleComboBox
                with QtCore.QSignalBlocker(selector):
                    selector.setCurrentIndex(selector.findData(previous_sample))
                return
        draft = self.window.project_data.segmentation_edit_sessions.get(sample_id)
        if draft is not None and draft.changed:
            with QtCore.QSignalBlocker(self.window.analysisProcessingTabs):
                self.window.analysisProcessingTabs.setCurrentWidget(self.window.analysisEditingPage)
        self.update_channels()
        self._refresh_reference_choices()
        self._refresh_masks()
        self._load_method_parameters()
        candidate = self.current_candidate()
        result = None if candidate is None else candidate.result
        if result is None:
            preview = self._preview()
            if preview is not None and preview.input_ref is not None:
                selector = self.window.analysisChNuclei
                with QtCore.QSignalBlocker(selector):
                    index = self._combo_index_for_data(selector, preview.input_ref)
                    if index >= 0:
                        selector.setCurrentIndex(index)
            self.clear_result_view()
        else:
            self.show_result(result, fit=self._result_sample_id != sample_id)

    def method_changed(self) -> None:
        """Choose inference options without changing the sample's active mask."""
        method_id = self.current_method_id()
        if method_id is not None:
            self.settings_dialog.set_method(method_id)
        self._load_method_parameters()
        self.set_busy(self.worker is not None)
        if self.current_candidate() is None:
            self.sample_changed()

    def refresh_result_view(self) -> None:
        """Keep the current segmentation view unless its result changes."""
        sample = self.current_sample()
        sample_id = None if sample is None else sample.sample_id
        candidate = self.current_candidate()
        result = None if candidate is None else candidate.result
        if (
            result is None
            or self.naparihelper is None
            or self._result_sample_id != sample_id
            or self._result_candidate_id != candidate.candidate_id
            or self._display_result is not result
        ):
            self.sample_changed()
            return

    def segmentation_parameters(self) -> SegmentationParameters:
        self.settings_dialog.set_method(self.current_method_id())
        return self.settings_dialog.parameters()

    def _set_segmentation_parameters(self, parameters: SegmentationParameters) -> None:
        self.settings_dialog.set_method(self.current_method_id())
        self.settings_dialog.set_parameters(parameters)

    def clear_result_view(self) -> None:
        if self.naparihelper is None:
            return
        self._edit_session = None
        sample = self.current_sample()
        sample_id = None if sample is None else sample.sample_id
        preview = self._preview()
        refs = () if preview is None else preview.reference_refs
        self.naparihelper.set_result(
            None,
            self._preview_input(),
            self._reference_maps(refs),
            fit=self._result_sample_id != sample_id or self.naparihelper.input_map is None,
        )
        self._result_sample_id = sample_id
        self._result_candidate_id = None
        self._display_result = None
        if preview is not None:
            self.naparihelper.apply_layer_settings(preview.layer_settings)
        self.window.analysisInfo.clear()
        self.window.analysisPostprocessing.setEnabled(False)
        self._update_overview()
        self.update_layer_controls()
        self.window.analysisExport.setEnabled(False)
        self.window.analysisSaveView.setEnabled(self.naparihelper.input_map is not None)
        self._refresh_reference_choices()
        self._update_edit_controls()

    def show_result(self, result: SegmentationResult, *, fit=True) -> None:
        window = self.window
        selector = window.analysisChNuclei
        index = self._combo_index_for_data(selector, result.input_ref)
        with QtCore.QSignalBlocker(selector):
            if index >= 0:
                selector.setCurrentIndex(index)

        if self.naparihelper is None:
            return
        if self._editing_mode():
            self._start_editing()
        self._display_result = None
        self.naparihelper.set_result(
            result,
            self._input_map(result),
            self._reference_maps(result.reference_refs),
            fit=fit,
            comparisons=self._comparisons(),
            edit_session=self._edit_session if self._editing_mode() else None,
        )
        self.naparihelper.apply_layer_settings(result.layer_settings)
        self._edit_tool_changed()
        self._display_result = result
        self._result_sample_id = result.sample_id
        candidate = self.current_candidate()
        self._result_candidate_id = None if candidate is None else candidate.candidate_id
        with QtCore.QSignalBlocker(window.analysisMinimumArea):
            window.analysisMinimumArea.setValue(result.postprocessing.minimum_area)
        with QtCore.QSignalBlocker(window.analysisExpansion):
            window.analysisExpansion.setValue(result.postprocessing.expansion)
        window.analysisPostprocessing.setEnabled(self.worker is None and not self._editing_mode())
        self._update_edit_controls()
        self._update_overview()
        self._refresh_reference_choices()
        self.update_layer_controls()
        window.analysisExport.setEnabled(True)
        window.analysisSaveView.setEnabled(True)

    def _preview_input(self):
        """Read the selected input for inspection before a method has produced labels."""
        ref = self.window.analysisChNuclei.currentData()
        if ref is None:
            return None
        try:
            return self.window.element_controller.ensure_settings(ref).data
        except (SourceUnavailableError, KeyError, RuntimeError, ValueError):
            return None

    def _input_changed(self):
        if self.naparihelper is not None and self._display_result is None:
            preview = self._preview()
            if preview is not None:
                preview.input_ref = self.window.analysisChNuclei.currentData()
                self.window.project_state_manager.project_changed()
            self.clear_result_view()
        self._refresh_reference_choices()

    def _reference_refs(self):
        if self._display_result is not None:
            return self._display_result.reference_refs
        preview = self._preview()
        return () if preview is None else preview.reference_refs

    def _preview(self, *, create=False):
        """Use saved inspection state only while this sample/method has no result."""
        sample = self.current_sample()
        method = self.current_method_id()
        if sample is None or method is None:
            return None
        previews = self.window.project_data.segmentation_previews
        if create:
            return previews.setdefault(sample.sample_id, {}).setdefault(
                method, SegmentationPreview()
            )
        return previews.get(sample.sample_id, {}).get(method)

    def _refresh_reference_choices(self):
        """Offer sample-local maps not already present as input or reference layers."""
        selector = self.window.analysisReferenceCombo
        previous = selector.currentData()
        excluded = {*self._reference_refs(), self.window.analysisChNuclei.currentData()}
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            sample = self.current_sample()
            if sample is not None:
                for channel in sorted(sample.channels.values(), key=lambda c: c.name.casefold()):
                    if channel.ref not in excluded:
                        selector.addItem(channel.name, channel.ref)
            index = selector.findData(previous)
            if index >= 0:
                selector.setCurrentIndex(index)
        self.window.analysisAddReference.setEnabled(selector.count() > 0 and self.worker is None)

    def _reference_maps(self, refs):
        """Resolve optional display maps without changing the segmentation input."""
        maps = []
        for ref in refs:
            try:
                settings = self.window.element_controller.ensure_settings(ref)
                maps.append((ref, settings.name, settings.transformedData()))
            except (SourceUnavailableError, KeyError, RuntimeError, ValueError):
                continue
        return maps

    def _add_reference(self):
        ref = self.window.analysisReferenceCombo.currentData()
        if ref is not None:
            self._set_reference_refs((*self._reference_refs(), ref))

    def _remove_reference(self, ref):
        self._set_reference_refs(tuple(item for item in self._reference_refs() if item != ref))

    def _set_reference_refs(self, refs):
        result = self._display_result
        self._layer_settings_changed()
        presentation = self.naparihelper.layer_settings()
        if result is not None:
            result.reference_refs = tuple(refs)
            self.show_result(result, fit=False)
            self._layer_settings_changed()
            self.window.project_state_manager.project_changed()
        else:
            preview = self._preview(create=True)
            if preview is None:
                return
            preview.reference_refs = tuple(refs)
            preview.input_ref = self.window.analysisChNuclei.currentData()
            preview.layer_settings = presentation
            self.clear_result_view()
            preview.layer_settings = self.naparihelper.layer_settings()
            self.window.project_state_manager.project_changed()
        self._refresh_reference_choices()

    def _postprocessing_changed(self, _value):
        """Recompute the disposable filtered result while preserving layer presentation."""
        result = self._display_result
        if result is None:
            return
        self._layer_settings_changed()
        result.postprocessing = SegmentationPostprocessing(
            self.window.analysisMinimumArea.value(), self.window.analysisExpansion.value()
        )
        self.show_result(result, fit=False)
        self.window.project_state_manager.project_changed()
        self.window.segmentationResultsChanged.emit()

    def _show_overview(self):
        self.window.analysisInfoStack.setCurrentWidget(self.window.analysisOverview)

    def _reload_plot_appearance(self):
        color = self.window.palette().text().color()
        for name in ("bottom", "left"):
            axis = self._area_plot.getAxis(name)
            axis.setPen(color)
            axis.setTextPen(color)
        for curve in self._area_plot.listDataItems():
            curve.setPen(color)

    def _update_overview(self, *, show=True):
        result = self._display_result
        self._area_plot.clear()
        if result is None:
            self.window.analysisSummary.setText("No segmentation result")
        else:
            session = self._edit_session if self._editing_mode() else None
            _ids, areas = result.segment_areas if session is None else session.areas
            resolution, unit = self.window.project_data.image_defaults.resolution
            units = list(DISPLAY_UNITS)
            area_unit = units[min(units.index(unit) + 1, len(units) - 1)]
            pixel_area = (resolution * DISPLAY_UNITS[unit] / DISPLAY_UNITS[area_unit]) ** 2
            total = result.processed_labels.size
            statistics = [("Total", areas.sum())]
            statistics.extend(
                (name, function(areas) if len(areas) else None)
                for name, function in (
                    ("Minimum", np.min),
                    ("Maximum", np.max),
                    ("Mean", np.mean),
                    ("Median", np.median),
                )
            )
            rows = "".join(
                f'<tr><td>{name}</td><td align="right">{format(area, ".1f" if name == "Mean" else "g")}</td>'
                f'<td align="right">{100 * area / total:.3g}%</td>'
                f'<td align="right">{area * pixel_area:.5g}</td></tr>'
                if area is not None
                else f"<tr><td>{name}</td><td>—</td><td>—</td><td>—</td></tr>"
                for name, area in statistics
            )
            self.window.analysisSummary.setText(
                f'<table cellspacing="6"><tr><td colspan="4">Segments: {len(areas)}</td></tr>'
                '<tr><th></th><th align="right">px</th><th align="right">fraction</th>'
                f'<th align="right">{escape(area_unit)}²</th></tr>'
                f"{rows}</table>"
            )
            _unfiltered_ids, unfiltered_areas = (
                result.unfiltered_segment_areas if session is None else session.areas
            )
            if len(unfiltered_areas):
                values, counts = np.unique(unfiltered_areas, return_counts=True)
                x = np.repeat(np.r_[0, values], 2)[1:]
                y = np.repeat(np.r_[0, np.cumsum(counts)], 2)[:-1]
                self._area_plot.plot(x, y, pen=pg.mkPen(self.window.palette().text().color()))
                self._area_plot.setYRange(0, len(unfiltered_areas) * 1.05, padding=0)
                if session is None:
                    self._area_plot.addItem(
                        pg.InfiniteLine(
                            result.postprocessing.minimum_area,
                            angle=90,
                            movable=False,
                            pen=pg.mkPen(
                                self.window.palette().text().color(), style=QtCore.Qt.DashLine
                            ),
                        )
                    )
                self._area_plot.enableAutoRange(axis="x")
        if show:
            self._show_overview()

    def _input_map(self, result: SegmentationResult):
        """Resolve display data independently of the saved segmentation labels."""
        try:
            raw = self.window.element_controller.ensure_settings(result.input_ref).data
        except (SourceUnavailableError, KeyError, RuntimeError, ValueError):
            return None
        if raw.shape != result.output.labels.shape:
            self._append_status(
                "The source map size has changed; displaying segmentation labels only."
            )
            return None
        return raw

    def _layer_settings_changed(self) -> None:
        """Store the current viewer presentation in its sample/method result."""
        if self.naparihelper is None:
            return
        candidate = self.current_candidate()
        result = None if candidate is None else candidate.result
        if (
            result is None
            and self._display_result is None
            and self.naparihelper.input_map is not None
        ):
            preview = self._preview(create=True)
            if preview is not None:
                preview.input_ref = self.window.analysisChNuclei.currentData()
                preview.layer_settings = self.naparihelper.layer_settings()
                self.window.project_state_manager.project_changed()
            return
        if result is None or self._display_result is not result:
            return
        settings = self.naparihelper.layer_settings()
        history = self._history()
        for identity, presentation in tuple(settings.layers.items()):
            if identity.startswith("comparison:"):
                other = history.candidates.get(identity.removeprefix("comparison:"))
                if other is not None:
                    other.comparison_presentation = presentation
                settings.layers.pop(identity)
        if settings == result.layer_settings:
            self.window.project_state_manager.project_changed()
            return
        result.layer_settings = settings
        self.window.project_state_manager.project_changed()

    @staticmethod
    def _combo_index_for_data(combo, target) -> int:
        for index in range(combo.count()):
            if combo.itemData(index) == target:
                return index
        return -1

    def update_channels(self) -> None:
        """Update the input-map selector from the active sample."""
        channels = self._effective_channels()
        selector = self.window.analysisChNuclei
        selected_ref = selector.currentData()
        with QtCore.QSignalBlocker(selector):
            selector.clear()
            selector.addItem("None", None)
            for channel in channels:
                selector.addItem(channel.name, userData=channel.ref)
            index = self._combo_index_for_data(selector, selected_ref)
            if index >= 0:
                selector.setCurrentIndex(index)
        self._select_default_nuclei_channel(channels)

    def _select_default_nuclei_channel(self, channels=None) -> None:
        selector = self.window.analysisChNuclei
        if selector.currentData() is not None:
            return
        if channels is None:
            channels = self._effective_channels()
        index = next(
            (
                row
                for row, channel in enumerate(channels, start=1)
                if channel.key == "P" or channel.key.startswith("P_")
            ),
            -1,
        )
        if index >= 0:
            selector.setCurrentIndex(index)

    def _effective_channels(self):
        sample = self.current_sample()
        if sample is None:
            return []
        project_data = self.window.project_data
        return sorted(
            (
                channel
                for channel in sample.effective_channels(project_data.project_channels).values()
                if channel.ref in project_data.element_settings
            ),
            key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
        )

    def element_settings(self, refs):
        effective = {channel.ref: channel for channel in self._effective_channels()}
        settings = []
        for ref in refs:
            channel = effective.get(ref)
            if channel is None:
                raise ValueError("The selected analysis channel is no longer available")
            asset = self.window.project_data.assets.get(ref.source_id)
            if asset is None or not asset.is_available:
                source = self.window.project_data.sources.get(ref.source_id)
                if source is not None:
                    raise SourceUnavailableError(source)
                raise RuntimeError(f"Channel {channel.name!r} has no data file")
            settings.append(self.window.element_controller.ensure_settings(ref))
        return settings

    def update_layer_controls(self) -> None:
        self.window.analysisLayerList.rebuild()

    def set_busy(self, busy: bool) -> None:
        window = self.window
        for widget in (
            window.analysisRun,
            window.analysisPipelineComboBox,
            window.analysisMaskCombo,
            window.analysisKeepMask,
            window.analysisComparisonCombo,
            window.analysisAddComparison,
            window.analysisSampleComboBox,
            window.analysisChNuclei,
            window.analysisOptions,
            window.analysisReferenceCombo,
            window.analysisAddReference,
            self.settings_dialog,
        ):
            widget.setEnabled(not busy)
        window.analysisProgress.setRange(0, 0 if busy else 1)
        window.analysisProgress.setTextVisible(False)
        self._model_progress_phase = None
        window.analysisExport.setEnabled(
            not busy and self.naparihelper is not None and self.naparihelper.result is not None
        )
        window.analysisSaveView.setEnabled(
            not busy and self.naparihelper is not None and bool(self.naparihelper.user_layers())
        )
        method_id = self.current_method_id()
        window.analysisOptions.setEnabled(
            not busy and method_id is not None and segmentation_method(method_id).has_options
        )
        window.analysisAbort.setEnabled(busy)
        window.analysisPostprocessing.setEnabled(
            not busy and self._display_result is not None and not self._editing_mode()
        )
        self._update_edit_controls()
        if not busy:
            self._refresh_masks()
            self._refresh_reference_choices()

    def _model_progress(self, phase, completed, total) -> None:
        """Show bounded transfer/checksum progress using the existing progress bar."""
        if self.worker is None:
            return
        if phase != self._model_progress_phase:
            self._append_status(f"{phase} trained model")
            self._model_progress_phase = phase
        bar = self.window.analysisProgress
        bar.setRange(0, 1000)
        bar.setValue(round(1000 * completed / total))
        bar.setFormat(f"{completed / 1024**2:.0f} / {total / 1024**2:.0f} MiB")
        bar.setTextVisible(True)

    def _model_ready(self) -> None:
        self.window.analysisProgress.setTextVisible(False)
        self.window.analysisProgress.setRange(0, 0)

    def _append_status(self, message) -> None:
        self.window.analysisStatus.appendPlainText(strftime("[%T] ") + message)
        self.window.analysisStatus.ensureCursorVisible()

    def run(self) -> None:
        """Validate the selected sample and start its background segmentation."""
        window = self.window
        if self.worker is not None or window.clustering_controller.worker is not None:
            window.show_error("Another analysis is running.")
            return
        if not window.project_manager.require_project_directory(
            "Segmentation results are stored in the project directory."
        ):
            return

        window.analysisStatus.clear()
        self._append_status("Initializing")
        sample = self.current_sample()
        if sample is None:
            window.show_error("Select a sample first.")
            return
        analysis_sample_id = sample.sample_id
        method_id = self.current_method_id()
        if method_id is None:
            window.show_error("Select a segmentation method first.")
            return
        method = segmentation_method(method_id)
        unavailable_reason = method.unavailable_reason()
        if unavailable_reason is not None:
            window.show_error("The selected segmentation method is unavailable", unavailable_reason)
            return
        input_ref = window.analysisChNuclei.currentData()
        if input_ref is None:
            window.show_error("Select an input channel first.")
            return
        parameters = self.segmentation_parameters()
        preview = self._preview()
        try:
            input_settings = self.element_settings([input_ref])[0]
            image = input_settings.data
        except SourceUnavailableError as exc:
            window.show_source_unavailable(exc.source_id)
            return
        except (KeyError, RuntimeError, ValueError) as exc:
            window.show_error("Cannot start analysis", str(exc))
            return

        if self._finish_editing() is False:
            return
        window.analysisProcessingTabs.setCurrentWidget(window.analysisPostprocessingPage)
        thread = QtCore.QThread(window)
        worker = method.create_worker(
            image,
            parameters=parameters,
            model_directory=model_directory(window.settings),
        )
        worker.moveToThread(thread)
        worker.progress.connect(self._append_status)
        worker.model_progress.connect(self._model_progress)
        worker.model_ready.connect(self._model_ready)

        def worker_cleanup():
            self.worker = None
            self.thread = None
            self.set_busy(False)

        @QtCore.Slot()
        def on_finished(output):
            self._append_status("Saving results")
            history = window.project_data.segmentation_histories.get(analysis_sample_id)
            previous = None if history is None or history.active is None else history.active.result
            result = SegmentationResult(
                sample_id=analysis_sample_id,
                method_id=method_id,
                input_ref=input_ref,
                parameters=parameters,
                output=output,
                layer_settings=(
                    deepcopy(previous.layer_settings)
                    if previous is not None
                    else deepcopy(preview.layer_settings)
                    if preview is not None
                    else SegmentationLayerSettings()
                ),
                postprocessing=(
                    previous.postprocessing
                    if previous is not None
                    else SegmentationPostprocessing()
                ),
                reference_refs=(
                    previous.reference_refs
                    if previous is not None
                    else preview.reference_refs
                    if preview is not None
                    else ()
                ),
            )
            try:
                candidate = publish_segmentation(window.project_data, result, window.project_dir)
            except Exception as exc:
                self._append_status("Failed to save results")
                window.show_error("Saving segmentation results failed", str(exc))
                worker_cleanup()
                return
            window.project_state_manager.project_changed()
            window.segmentationResultsChanged.emit()
            self._append_status("Rendering results")
            self.show_result(candidate.result)
            worker_cleanup()
            self._append_status("Done")

        @QtCore.Slot()
        def on_failed(details):
            model_error = worker.model_error
            # A modal dialog can process thread deletion before returning.
            worker_cleanup()
            if details == "":
                self._append_status("Interrupted")
            else:
                self._append_status("Failed")
                if model_error is not None:
                    QtWidgets.QMessageBox.warning(
                        window, "Cannot obtain trained model", model_error
                    )
                else:
                    window.show_error("Analysis failed", details)

        self.set_busy(True)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.finished.connect(thread.quit, QtCore.Qt.DirectConnection)
        worker.failed.connect(thread.quit, QtCore.Qt.DirectConnection)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self.worker = worker
        self.thread = thread
        thread.start()

    def export_results(self) -> None:
        """Export edited instance labels before reversible post-processing."""
        if self.naparihelper is None or self.naparihelper.result is None:
            return
        window = self.window
        default_directory = window.project_manager.default_export_directory()
        if default_directory is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            window,
            "Choose export directory",
            default_directory,
        )
        if not directory:
            return
        window.settings.setValue(EXPORT_DIRECTORY_SETTING, directory)
        try:
            output = Path(directory) / strftime("export_%F_%H%M%S")
            output.mkdir(parents=True, exist_ok=True)
            imwrite(
                output / "nuclei_labels.tif",
                (
                    self._edit_session.labels
                    if self._edit_session is not None
                    else self.naparihelper.result.output.labels
                ),
                photometric="minisblack",
            )
        except Exception as exc:
            window.show_error("Export failed", str(exc))
            return
        message = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Information,
            "Export complete",
            f"Segmentation mask exported to:\n{output}",
            parent=window,
        )
        open_directory = message.addButton(
            "Open directory", QtWidgets.QMessageBox.ButtonRole.ActionRole
        )
        open_directory.setIcon(icons.icon(icons.IconName.FOLDER))
        message.addButton(QtWidgets.QMessageBox.StandardButton.Ok)
        message.exec()
        if message.clickedButton() is open_directory:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(output)))

    def save_current_view(self) -> None:
        """Save the currently displayed segmentation canvas as a PNG image."""
        if self.naparihelper is None or not self.naparihelper.user_layers():
            return
        window = self.window
        directory = window.project_manager.default_export_directory()
        if directory is None:
            return
        filename = window.askFileName(
            "Save current view",
            filter="PNG image (*.png)",
            settingname=EXPORT_DIRECTORY_SETTING,
            save=True,
            directory=directory,
            defaultfilename="segmentation.png",
        )
        if filename is None:
            return
        try:
            self.naparihelper.viewer.screenshot(
                path=filename,
                canvas_only=True,
                flash=True,
            )
        except Exception as exc:
            window.show_error("Saving the current view failed", str(exc))

    def clear_project(self) -> None:
        """Clear controller-owned derived display state for a new project."""
        self._edit_session = None
        with QtCore.QSignalBlocker(self.window.analysisProcessingTabs):
            self.window.analysisProcessingTabs.setCurrentWidget(
                self.window.analysisPostprocessingPage
            )
        self.window.analysisSampleComboBox.clear()
        if self.naparihelper is not None:
            self.naparihelper.reset_initial_fit()
            self.clear_result_view()
