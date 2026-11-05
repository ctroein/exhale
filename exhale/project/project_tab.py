"""Project-wide sample, file, map, and channel controls."""

import os
from pathlib import Path

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt

from .. import icons
from ..data.source_refs import SourceUnavailableError
from ..imaging.listwidgets import ElementListWidget
from ..widgets import IconCheckDelegate


class _SampleTreeDelegate(QtWidgets.QStyledItemDelegate):
    """Show a file's full path only while its abbreviated name is edited."""

    def __init__(self, project_tab):
        super().__init__(project_tab.sampleTree)
        self.project_tab = project_tab

    def setEditorData(self, editor, index):
        if (
            index.column() == 0
            and index.data(ProjectTab.NODE_KIND_ROLE) == "file"
            and isinstance(editor, QtWidgets.QLineEdit)
        ):
            asset_id = index.data(ProjectTab.NODE_ID_ROLE)
            editor.setText(self.project_tab.project.assets[asset_id].path)
            editor.selectAll()
            return
        super().setEditorData(editor, index)

    def paint(self, painter, option, index):
        if index.column() != 2 or index.data(ProjectTab.NODE_KIND_ROLE) != "sample":
            super().paint(painter, option, index)
            return
        label = index.data(Qt.DisplayRole)
        if " (+" not in label:
            super().paint(painter, option, index)
            return
        summary, counts = label.split(" (+", 1)
        added, removed = counts.rstrip(")").split(" -", 1)
        styled = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        style = styled.widget.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, styled, styled.widget)
        metrics = styled.fontMetrics
        baseline = rect.y() + (rect.height() + metrics.ascent() - metrics.descent()) // 2
        dark = styled.palette.color(QtGui.QPalette.Window).lightness() < 128
        base_color = styled.palette.color(
            QtGui.QPalette.HighlightedText
            if styled.state & QtWidgets.QStyle.State_Selected
            else QtGui.QPalette.Text
        )
        segments = (
            (summary + " (", base_color),
            ("+" + added, QtGui.QColor("#79bd85") if dark else QtGui.QColor("#286c37")),
            (" -" + removed, QtGui.QColor("#d98080") if dark else QtGui.QColor("#993939")),
            (")", base_color),
        )
        painter.save()
        painter.setClipRect(rect)
        x = rect.x()
        for text, color in segments:
            painter.setPen(color)
            painter.drawText(x, baseline, text)
            x += metrics.horizontalAdvance(text)
        painter.restore()


class ProjectTab(QtCore.QObject):
    """Coordinate Project data tab controls with the authoritative project model."""

    NODE_KIND_ROLE = Qt.UserRole
    NODE_ID_ROLE = Qt.UserRole + 1
    FILE_ICON_ROLE = Qt.UserRole + 2

    def __init__(self, window):
        super().__init__(window.projectDataTab)
        self.window = window
        self.project = window.project_data
        self.widget = window.projectDataTab
        self.splitter = window.projectDataSplitter
        for name in (
            "addProjectFilesButton",
            "addSampleFilesButton",
            "abundanceUnitsValue",
            "channelList",
            "dataRootValue",
            "projectDirectoryValue",
            "refreshChannelsButton",
            "removeButton",
            "resolutionUnits",
            "resolutionValue",
            "sampleTree",
        ):
            setattr(self, name, getattr(window, name))
        self.widget.installEventFilter(self)
        self._sample_tree_viewport = self.sampleTree.viewport()
        self._sample_tree_viewport.installEventFilter(self)
        self.channelList.installEventFilter(self)
        self.channelList.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.channelList.setRootIsDecorated(False)
        self.channelList.setItemDelegateForColumn(0, IconCheckDelegate(self.channelList))
        self.channelList.header().setStretchLastSection(False)
        self.channelList.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.channelList.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.refreshChannelsButton.setIcon(icons.icon(icons.IconName.REFRESH))
        self.addProjectFilesButton.setIcon(icons.icon(icons.IconName.FILE_DATA))
        self.addSampleFilesButton.setIcon(icons.icon(icons.IconName.FILE))
        self.removeButton.setIcon(icons.icon(icons.IconName.DELETE))
        self.sampleTree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.sampleTree.setItemDelegate(_SampleTreeDelegate(self))
        for column in range(3):
            self.sampleTree.header().setSectionResizeMode(column, QtWidgets.QHeaderView.Interactive)
        header = self.sampleTree.header()
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._tree_section_resized)
        self._tree_widths_initialized = False
        self._maps_column_min_width = 0
        self._size_column_min_width = 0

        self.sampleTree.currentItemChanged.connect(self._tree_selection_changed)
        self.sampleTree.itemDoubleClicked.connect(self._begin_tree_edit)
        self.sampleTree.itemChanged.connect(self._tree_item_changed)
        self.channelList.itemChanged.connect(self._project_channel_check_changed)
        self.refreshChannelsButton.clicked.connect(self.refresh_channels)
        self.addProjectFilesButton.clicked.connect(window.source_manager.select_and_open_files)
        self.addSampleFilesButton.clicked.connect(self._add_files_to_sample)
        self.removeButton.clicked.connect(self._remove_selected)
        self.resolutionValue.valueChanged.connect(self._resolution_changed)
        self.resolutionUnits.currentTextChanged.connect(self._resolution_changed)
        self.abundanceUnitsValue.textEdited.connect(self._abundance_units_changed)
        self._sync_resolution_controls()
        self._sync_abundance_units_control()

    def eventFilter(self, watched, event):
        if watched is self.widget and event.type() == QtCore.QEvent.Show:
            self.refresh_channels()
            QtCore.QTimer.singleShot(0, self._initialize_tree_widths)
        elif (
            watched is self._sample_tree_viewport
            and event.type() == QtCore.QEvent.Resize
            and self._tree_widths_initialized
        ):
            self._fit_tree_columns(event.size().width())
        elif (
            watched is self.channelList
            and event.type() == QtCore.QEvent.KeyPress
            and event.key() == Qt.Key_Space
        ):
            current = self.channelList.currentItem()
            if current is not None:
                selected = self.channelList.selectedItems() or [current]
                self._set_project_channels(
                    selected, current.checkState(0) == Qt.CheckState.Unchecked
                )
            return True
        return super().eventFilter(watched, event)

    def selected_sample_id(self):
        item = self.sampleTree.currentItem()
        if item is None:
            return None
        while item.parent() is not None:
            item = item.parent()
        return item.data(0, self.NODE_ID_ROLE)

    def selected_asset_id(self):
        item = self.sampleTree.currentItem()
        if item is None or item.data(0, self.NODE_KIND_ROLE) != "file":
            return None
        return item.data(0, self.NODE_ID_ROLE)

    def refresh(self, selected=None):
        selected = selected or self.selected_sample_id()
        selected_asset = self.selected_asset_id()
        existing_samples = {
            item.data(0, self.NODE_ID_ROLE)
            for row in range(self.sampleTree.topLevelItemCount())
            if (item := self.sampleTree.topLevelItem(row)) is not None
        }
        expanded_samples = {
            item.data(0, self.NODE_ID_ROLE)
            for row in range(self.sampleTree.topLevelItemCount())
            if (item := self.sampleTree.topLevelItem(row)).isExpanded()
        }
        paths = [asset.path for asset in self.project.assets.values()]
        labels, _common_root = self._path_labels(paths)
        self.projectDirectoryValue.setText(
            str(self.window.project_dir)
            if self.window.project_dir is not None
            else "Unsaved project"
        )
        data_root = self.project.external_data_root
        self.dataRootValue.setText(str(data_root) if data_root is not None else "—")
        self.dataRootValue.setToolTip(self.dataRootValue.text())

        with QtCore.QSignalBlocker(self.sampleTree):
            self.sampleTree.clear()
            selected_item = None
            for sample in self.project.samples.values():
                sample_item = QtWidgets.QTreeWidgetItem(
                    [sample.name, self._sample_size(sample), self._map_count(sample)]
                )
                sample_item.setFlags(sample_item.flags() | Qt.ItemFlag.ItemIsEditable)
                sample_item.setData(0, self.NODE_KIND_ROLE, "sample")
                sample_item.setData(0, self.NODE_ID_ROLE, sample.sample_id)
                sample_item.setToolTip(2, self._map_count_tooltip(sample))
                self.sampleTree.addTopLevelItem(sample_item)
                if sample.sample_id == selected:
                    selected_item = sample_item
                for asset_id in sample.asset_ids:
                    asset = self.project.assets[asset_id]
                    channels = [
                        channel
                        for channel in sample.channels.values()
                        if channel.ref is not None and channel.ref.source_id == asset_id
                    ]
                    single_map_tiff = asset.source.kind == "tiff" and len(channels) == 1
                    multichannel_tiff = asset.source.kind == "tiff" and len(channels) > 1
                    name = labels.get(asset.path, Path(asset.path).name)
                    if not asset.is_available:
                        name += " [unavailable]"
                    file_item = QtWidgets.QTreeWidgetItem(
                        [name, "", channels[0].key if single_map_tiff else ""]
                    )
                    file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    if single_map_tiff:
                        icon_name = icons.IconName.FILE_SINGLECHANNEL_IMAGE
                    elif multichannel_tiff:
                        icon_name = icons.IconName.FILE_MULTICHANNEL_IMAGE
                    else:
                        icon_name = icons.IconName.FILE_DATA
                    file_item.setIcon(0, icons.icon(icon_name))
                    file_item.setData(0, self.NODE_KIND_ROLE, "file")
                    file_item.setData(0, self.NODE_ID_ROLE, asset_id)
                    file_item.setData(0, self.FILE_ICON_ROLE, icon_name.value)
                    file_item.setToolTip(0, asset.path)
                    sample_item.addChild(file_item)
                    if asset_id == selected_asset:
                        selected_item = file_item
                sample_item.setExpanded(
                    sample.sample_id in expanded_samples or sample.sample_id not in existing_samples
                )
            if selected_item is None and self.sampleTree.topLevelItemCount():
                selected_item = self.sampleTree.topLevelItem(0)
            self.sampleTree.setCurrentItem(selected_item)
        self.refresh_channels()
        self._update_selection_controls()
        self._sync_resolution_controls()
        self._sync_abundance_units_control()

    def _initialize_tree_widths(self):
        if self._tree_widths_initialized:
            return
        header = self.sampleTree.header()
        metrics = header.fontMetrics()
        padding = metrics.horizontalAdvance("  ") + 24
        maps_width = (
            max(
                metrics.horizontalAdvance(header.model().headerData(2, Qt.Horizontal)),
                metrics.horizontalAdvance("000/000 (+00 -00)"),
            )
            + padding
        )
        self._maps_column_min_width = maps_width
        self._size_column_min_width = metrics.horizontalAdvance("00000×00000") + padding
        self._size_column_width = self._size_column_min_width
        self._maps_column_width = self._maps_column_min_width
        self._tree_widths_initialized = True
        self._fit_tree_columns()

    def _tree_section_resized(self, logical_index, _old_size, new_size):
        if not self._tree_widths_initialized:
            return
        if logical_index == 1:
            self._size_column_width = new_size
        elif logical_index == 2:
            self._maps_column_width = new_size
        self._fit_tree_columns()

    def _fit_tree_columns(self, total=None):
        """Give the summary columns enough room and leave remaining space for names."""
        if total is None:
            total = self.sampleTree.viewport().width()
        if total <= 0:
            return
        minimum = self.sampleTree.header().minimumSectionSize()
        size_width = max(minimum, self._size_column_width)
        maps_width = max(minimum, self._maps_column_width)
        name_width = max(minimum, total - size_width - maps_width)
        with QtCore.QSignalBlocker(self.sampleTree.header()):
            self.sampleTree.setColumnWidth(0, name_width)
            self.sampleTree.setColumnWidth(1, size_width)
            self.sampleTree.setColumnWidth(2, maps_width)

    @staticmethod
    def _path_labels(paths):
        if not paths:
            return {}, None
        try:
            resolved = {path: Path(path).resolve() for path in paths}
            common = Path(os.path.commonpath([str(path.parent) for path in resolved.values()]))
            relative = {key: path.relative_to(common) for key, path in resolved.items()}
        except (ValueError, OSError):
            common = None
            relative = {}
        if relative and max(len(path.parts) for path in relative.values()) <= 3:
            return {key: str(value) for key, value in relative.items()}, common
        return {path: Path(path).name for path in paths}, common

    def refresh_channels(self):
        current = self.channelList.currentItem()
        current_key = (
            None if current is None else current.data(0, ElementListWidget.CHANNEL_KEY_ROLE)
        )
        keys = {key for sample in self.project.samples.values() for key in sample.channels}
        ordered = sorted(
            keys, key=lambda key: (key not in self.project.project_channels, key.casefold())
        )
        with QtCore.QSignalBlocker(self.channelList):
            self.channelList.clear()
            selected_item = None
            for key in ordered:
                project_channel = self.project.project_channels.get(key)
                available = next(
                    sample.channels[key]
                    for sample in self.project.samples.values()
                    if key in sample.channels
                )
                name = project_channel.name if project_channel is not None else available.name
                text = key if name == key else f"{name} [{key}]"
                enabled = project_channel is not None
                item = QtWidgets.QTreeWidgetItem([text, ""])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                item.setData(0, ElementListWidget.CHANNEL_KEY_ROLE, key)
                item.setData(0, ElementListWidget.ELEMENT_REF_ROLE, available.ref)
                self.channelList.addTopLevelItem(item)
                if key == current_key:
                    selected_item = item
            self.channelList.setCurrentItem(selected_item)
        self.refresh_channel_counts()

    def refresh_channel_counts(self):
        """Update per-element availability and override explanations without moving rows."""
        samples = list(self.project.samples.values())
        total = len(samples)
        with QtCore.QSignalBlocker(self.channelList):
            for row in range(self.channelList.topLevelItemCount()):
                item = self.channelList.topLevelItem(row)
                key = item.data(0, ElementListWidget.CHANNEL_KEY_ROLE)
                present = sum(self._has_map(sample, key) for sample in samples)
                default_enabled = key in self.project.project_channels
                included = sum(
                    self._has_map(sample, key)
                    and not default_enabled
                    and key in sample.channel_overrides
                    and sample.channel_overrides[key] is not None
                    for sample in samples
                )
                excluded = sum(
                    self._has_map(sample, key)
                    and default_enabled
                    and key in sample.channel_overrides
                    and sample.channel_overrides[key] is None
                    for sample in samples
                )
                item.setText(1, f"{present}/{total}")
                tooltip = (
                    f"Available: {present}/{total} samples\n"
                    f"Project default: {'included' if default_enabled else 'excluded'}\n"
                    f"Sample {'exclusions' if default_enabled else 'inclusions'}: "
                    f"{excluded if default_enabled else included}"
                )
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)

    @staticmethod
    def _has_map(sample, key):
        channel = sample.channels.get(key)
        return channel is not None and channel.ref is not None

    def reload_icons(self):
        """Reload palette-dependent icons used by the project-data controls."""
        self.addProjectFilesButton.setIcon(icons.icon(icons.IconName.FILE_DATA))
        self.addSampleFilesButton.setIcon(icons.icon(icons.IconName.FILE))
        self.removeButton.setIcon(icons.icon(icons.IconName.DELETE))
        self.refreshChannelsButton.setIcon(icons.icon(icons.IconName.REFRESH))
        self.channelList.viewport().update()
        with QtCore.QSignalBlocker(self.sampleTree):
            for row in range(self.sampleTree.topLevelItemCount()):
                sample_item = self.sampleTree.topLevelItem(row)
                for child_row in range(sample_item.childCount()):
                    file_item = sample_item.child(child_row)
                    icon_name = icons.IconName(file_item.data(0, self.FILE_ICON_ROLE))
                    file_item.setIcon(0, icons.icon(icon_name))

    def _tree_selection_changed(self):
        self._update_selection_controls()

    def _update_selection_controls(self):
        sample_id = self.selected_sample_id()
        sample = self.project.samples.get(sample_id)
        item = self.sampleTree.currentItem()
        self.addSampleFilesButton.setEnabled(sample is not None)
        self.removeButton.setEnabled(sample is not None and item is not None)

    def _begin_tree_edit(self, item, column):
        kind = item.data(0, self.NODE_KIND_ROLE)
        if (kind == "sample" and column == 0) or (kind == "file" and column == 0):
            self.sampleTree.editItem(item, column)

    def _tree_item_changed(self, item, column):
        kind = item.data(0, self.NODE_KIND_ROLE)
        try:
            if kind == "sample" and column == 0:
                self.project.rename_sample(item.data(0, self.NODE_ID_ROLE), item.text(0).strip())
                self.window.element_controller.refresh_sample_selector(
                    item.data(0, self.NODE_ID_ROLE)
                )
            elif kind == "file" and column == 0:
                asset_id = item.data(0, self.NODE_ID_ROLE)
                filename = item.text(0).strip()
                sample_id = self.selected_sample_id()
                QtCore.QTimer.singleShot(
                    0,
                    lambda: self._finish_path_edit(asset_id, filename, sample_id),
                )
                return
            else:
                return
        except Exception as exc:
            self.window.show_error("Editing failed", str(exc))
            self.refresh(self.selected_sample_id())
            return
        self._mark_changed()

    def _finish_path_edit(self, asset_id, filename, sample_id):
        asset = self.project.assets.get(asset_id)
        if asset is None:
            return
        if filename == asset.path:
            self.refresh(sample_id)
            return
        if not self.window.source_manager.replace_project_asset_path(asset_id, filename):
            self.refresh(sample_id)

    def _set_project_channels(self, items, enabled):
        changed = False
        with QtCore.QSignalBlocker(self.channelList):
            for item in items:
                key = item.data(0, ElementListWidget.CHANNEL_KEY_ROLE)
                ref = item.data(0, ElementListWidget.ELEMENT_REF_ROLE)
                if enabled:
                    try:
                        settings = self.window.element_controller.ensure_settings(ref)
                    except SourceUnavailableError as exc:
                        self.window.show_source_unavailable(exc.source_id)
                        item.setCheckState(
                            0,
                            Qt.CheckState.Checked
                            if key in self.project.project_channels
                            else Qt.CheckState.Unchecked,
                        )
                        continue
                    _sample, channel = self.project.channel_for_ref(ref)
                    channel.settings = settings
                    self.project.add_project_channel(key, channel.name, settings)
                else:
                    self.project.remove_project_channel(key)
                changed = True
                item.setCheckState(0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        if not changed:
            return
        self.window.element_controller.effective_channels_changed()
        self.window.element_controller.sample_changed()
        self.refresh_map_counts()
        self.refresh_channel_counts()
        self._mark_changed()

    def _project_channel_check_changed(self, item, column):
        if column != 0:
            return
        self._set_project_channels([item], item.checkState(0) == Qt.CheckState.Checked)

    def refresh_map_counts(self):
        for row in range(self.sampleTree.topLevelItemCount()):
            item = self.sampleTree.topLevelItem(row)
            sample = self.project.samples[item.data(0, self.NODE_ID_ROLE)]
            item.setText(2, self._map_count(sample))
            item.setToolTip(2, self._map_count_tooltip(sample))

    def _map_count_tooltip(self, sample):
        project_keys = self.project.project_channels
        effective = sample.effective_channels(project_keys)
        unavailable = sum(not self._has_map(sample, key) for key in project_keys)
        project_included = sum(key in effective for key in project_keys)
        project_excluded = len(project_keys) - project_included - unavailable
        extra_included = sum(key not in project_keys for key in effective)
        return (
            f"Project elements: {project_included} included, {unavailable} unavailable, "
            f"{project_excluded} excluded.\nExtra elements: {extra_included} included."
        )

    @staticmethod
    def _sample_size(sample):
        return f"{sample.shape[1]}×{sample.shape[0]}" if sample.shape is not None else "—"

    def _map_count(self, sample):
        included, available, added, removed = self._map_counts(sample)
        suffix = f" (+{added} -{removed})" if added or removed else ""
        return f"{included}/{available}{suffix}"

    def _map_counts(self, sample):
        project_keys = self.project.project_channels
        included = len(sample.effective_channels(project_keys))
        added = sum(
            self._has_map(sample, key) and key not in project_keys and override is not None
            for key, override in sample.channel_overrides.items()
        )
        removed = sum(
            self._has_map(sample, key) and key in project_keys and override is None
            for key, override in sample.channel_overrides.items()
        )
        return included, len(sample.channels), added, removed

    def _resolution_changed(self, *_):
        self.project.image_defaults.setResolution(
            self.resolutionValue.value(), self.resolutionUnits.currentText()
        )
        for image in self.window.project_data.images.values():
            image.resolution = list(self.project.image_defaults.resolution)
        self._mark_changed()

    def _sync_resolution_controls(self):
        value, units = self.project.image_defaults.resolution
        with QtCore.QSignalBlocker(self.resolutionValue):
            self.resolutionValue.setValue(value)
        with QtCore.QSignalBlocker(self.resolutionUnits):
            self.resolutionUnits.setCurrentText(units)

    def _abundance_units_changed(self, value):
        self.project.abundance_units = value
        if self.window.analysis_controller.naparihelper is not None:
            self.window.analysis_controller.naparihelper.abundance_units = value
        if self.window.clustering_controller.naparihelper is not None:
            self.window.clustering_controller.naparihelper.abundance_units = value
        self._mark_changed()

    def _sync_abundance_units_control(self):
        with QtCore.QSignalBlocker(self.abundanceUnitsValue):
            self.abundanceUnitsValue.setText(self.project.abundance_units)

    def _add_files_to_sample(self):
        sample_id = self.selected_sample_id()
        if sample_id is None:
            return
        filenames = self.window.source_manager.select_file_names("Add files to sample")
        if filenames:
            self.window.source_manager.open_files(filenames, sample_id=sample_id)

    def _remove_selected(self):
        sample_id = self.selected_sample_id()
        asset_id = self.selected_asset_id()
        if sample_id is None:
            return
        subject = (
            Path(self.project.assets[asset_id].path).name
            if asset_id is not None
            else self.project.samples[sample_id].name
        )
        if (
            QtWidgets.QMessageBox.question(
                self.window, "Remove project data", f"Remove {subject!r} from the project?"
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        if asset_id is not None:
            self.window.source_manager.remove_project_asset(asset_id)
        else:
            self.window.source_manager.remove_project_sample(sample_id)

    def _mark_changed(self):
        if hasattr(self.window, "project_state_manager"):
            self.window.project_state_manager.project_changed()
