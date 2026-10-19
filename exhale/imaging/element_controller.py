"""Controller for sample-channel selection and element-map editing."""

from __future__ import annotations

from functools import partial

import numpy as np
from qtpy import QtCore
from qtpy.QtCore import Qt

from ..data.elementsettings import ElementSettings, Normalizers
from ..data.projectdata import SampleChannelState, shortest_unique_path_suffixes
from ..data.source_refs import ElementRef, SourceUnavailableError
from .listwidgets import ElementListWidget, ImageListWidget


class ElementController:
    """Own the Element maps tab's sample, channel, and editor state."""

    def __init__(self, window):
        self.window = window
        self.current_element = None
        self._editing_channel_context = None
        self._settings_failures = {}

    def setup(self) -> None:
        """Connect element-map controls and initialize their choices."""
        window = self.window
        element_list = window.elementList
        element_list.use_sample_check_delegate()
        window.loadedFileComboBox.currentIndexChanged.connect(self.sample_changed)
        element_list.itemUnwanted.connect(self.skip_sample_element)
        element_list.stateToggleRequested.connect(self.cycle_sample_element_state)
        element_list.currentItemChanged.connect(self._current_item_changed)
        window.elementName.editingFinished.connect(self._name_changed)

        for normalizer in Normalizers:
            window.elementNormalizer.addItem(normalizer.description)
        window.elementNormalizer.currentIndexChanged.connect(self._normalizer_changed)
        window.gammaValue.valueChanged.connect(self._gamma_changed)

        window.elementNormalizeRange = [window.elementNormalizeMin, window.elementNormalizeMax]
        for bound in range(2):
            window.elementNormalizeRange[bound].valueChanged.connect(
                partial(self._range_changed, bound)
            )
        window.elementSDButton.clicked.connect(partial(self._set_range_by_mode, "sd"))
        window.elementPercButton.clicked.connect(partial(self._set_range_by_mode, "percent"))
        window.elementHistogramPlot.limitsChanged.connect(self._histogram_limits_changed)
        window.elementHistogramPlot.histogramRangeRequested.connect(self._histogram_range_requested)

    def current_sample(self):
        sample_id = self.window.loadedFileComboBox.currentData()
        return self.window.project_data.samples.get(sample_id)

    def ensure_settings(self, ref):
        project_data = self.window.project_data
        if ref in project_data.element_settings:
            return project_data.element_settings[ref]
        source = project_data.sources[ref.source_id]
        if not source.is_open:
            raise SourceUnavailableError(source)
        _sample, channel = project_data.channel_for_ref(ref)
        settings = ElementSettings(
            ref=ref,
            name=channel.name,
            data=channel.data_source,
            defaults=project_data.element_defaults,
        )
        project_data.set_element_settings(ref, settings)
        return settings

    def effective_channels_changed(self) -> None:
        """Reconcile dependent state after effective channel choices change."""
        window = self.window
        changed_images = set()
        for image_id, image in window.project_data.images.items():
            sample = window.project_data.samples.get(image.sample_id)
            available_keys = (
                ()
                if sample is None
                else sample.effective_channels(window.project_data.project_channels)
            )
            if image.reconcileChannels(available_keys):
                changed_images.add(image_id)

        failures = []
        for ref in window.project_data.effective_refs():
            if ref in self._settings_failures:
                continue
            try:
                self.ensure_settings(ref)
            except Exception as exc:
                self._settings_failures[ref] = str(exc)
                failures.append((ref, exc))
        window.channelsChanged.emit()
        current_item = window.imageList.currentItem()
        current_image_id = (
            None if current_item is None else current_item.data(ImageListWidget.IMG_NUM_ROLE)
        )
        if current_image_id in changed_images:
            window.image_controller.show_image(current_image_id)
            window.image_controller.update_composed_image(reset_view=True)
        if failures:
            unavailable = next(
                (exc for _ref, exc in failures if isinstance(exc, SourceUnavailableError)),
                None,
            )
            if unavailable is not None:
                window.show_source_unavailable(unavailable.source_id)
                failures = [
                    (ref, exc)
                    for ref, exc in failures
                    if not isinstance(exc, SourceUnavailableError)
                ]
        if failures:
            error = next(
                (exc for _ref, exc in failures if "requires the 'imagecodecs' package" in str(exc)),
                failures[0][1],
            )
            window.show_tiff_read_error(sorted({ref.source_id for ref, _exc in failures}), error)

    @staticmethod
    def channel_list_label(key, name):
        return key if name == key else f"{name} [{key}]"

    def refresh_sample_selector(self, selected=None) -> None:
        window = self.window
        if selected is None:
            selected = window.loadedFileComboBox.currentData()
        samples = list(window.project_data.samples.values())
        paths = [
            window.project_data.assets[sample.asset_ids[0]].path
            for sample in samples
            if sample.asset_ids
        ]
        suffixes = shortest_unique_path_suffixes(paths) if paths else {}
        name_counts = {}
        for sample in samples:
            name_counts[sample.name] = name_counts.get(sample.name, 0) + 1

        entries = []
        for sample in samples:
            label = sample.name
            if name_counts[label] > 1 and sample.asset_ids:
                path = window.project_data.assets[sample.asset_ids[0]].path
                label = f"{label} — {suffixes[path]}"
            entries.append((label, sample.sample_id))

        with QtCore.QSignalBlocker(window.loadedFileComboBox):
            window.loadedFileComboBox.clear()
            for label, sample_id in entries:
                window.loadedFileComboBox.addItem(label, sample_id)
            index = window.loadedFileComboBox.findData(selected)
            window.loadedFileComboBox.setCurrentIndex(
                index if index >= 0 else (0 if samples else -1)
            )
        window.analysis_controller.refresh_samples(entries, selected)
        window.project_tab.refresh(selected)
        self.sample_changed()

    def sample_changed(self) -> None:
        """Update the channels and element editor for the selected sample."""
        window = self.window
        sample = self.current_sample()
        window.label.setText("Sample elements")
        window.addImageButton.setEnabled(sample is not None)
        window.image_controller.refresh_list(None if sample is None else sample.sample_id)

        self.clear_selection()
        with QtCore.QSignalBlocker(window.elementList):
            window.elementList.clear()
            if sample is None:
                keys = {
                    key for item in window.project_data.samples.values() for key in item.channels
                }
                for key in sorted(keys, key=str.casefold):
                    project_channel = window.project_data.project_channels.get(key)
                    available = next(
                        item.channels[key]
                        for item in window.project_data.samples.values()
                        if key in item.channels
                    )
                    name = project_channel.name if project_channel is not None else available.name
                    window.elementList.addChannel(
                        self.channel_list_label(key, name),
                        key,
                        available.ref,
                        Qt.CheckState.Checked
                        if project_channel is not None
                        else Qt.CheckState.Unchecked,
                    )
                window.channelsChanged.emit()
                return

            keys = sorted(
                sample.channels,
                key=lambda key: (key not in window.project_data.project_channels, key.casefold()),
            )
            has_project_elements = any(key in window.project_data.project_channels for key in keys)
            divider_added = False
            for key in keys:
                channel = sample.channels[key]
                state = window.project_data.sample_channel_state(sample.sample_id, key)
                deferred = key not in sample.channel_overrides
                if state == SampleChannelState.INHERIT:
                    name = window.project_data.project_channels[key].name
                elif state == SampleChannelState.OVERRIDE:
                    override = sample.channel_overrides[key]
                    name = override.name or channel.name
                else:
                    name = channel.name
                window.elementList.addSampleChannel(
                    self.channel_list_label(key, name),
                    key,
                    channel.ref,
                    state,
                    deferred=deferred,
                    project_enabled=key in window.project_data.project_channels,
                    group_divider=(
                        has_project_elements
                        and key not in window.project_data.project_channels
                        and not divider_added
                    ),
                )
                if key not in window.project_data.project_channels:
                    divider_added = True
        window.channelsChanged.emit()

    def refresh_current_channel_states(self) -> None:
        sample = self.current_sample()
        if sample is None:
            return
        with QtCore.QSignalBlocker(self.window.elementList):
            for row in range(self.window.elementList.count()):
                item = self.window.elementList.item(row)
                key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
                state = self.window.project_data.sample_channel_state(sample.sample_id, key)
                ElementListWidget.updateSampleChannel(
                    item,
                    state,
                    deferred=key not in sample.channel_overrides,
                    project_enabled=key in self.window.project_data.project_channels,
                )

    def cycle_sample_element_state(self, item) -> None:
        sample = self.current_sample()
        if sample is None:
            return
        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
        if key not in sample.channel_overrides:
            try:
                settings = self.ensure_settings(ref)
            except SourceUnavailableError as exc:
                self.window.show_source_unavailable(exc.source_id)
                return
            self.window.project_data.override_sample_channel(
                sample.sample_id, key, settings=settings
            )
        elif sample.channel_overrides[key] is not None:
            self.window.project_data.skip_sample_channel(sample.sample_id, key)
        else:
            self.window.project_data.revert_sample_channel(sample.sample_id, key)
        self._finish_channel_state_change()

    def skip_sample_element(self, item) -> None:
        sample = self.current_sample()
        if sample is None:
            return
        key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
        self.window.project_data.skip_sample_channel(sample.sample_id, key)
        self._finish_channel_state_change()

    def _finish_channel_state_change(self) -> None:
        self.effective_channels_changed()
        self.refresh_current_channel_states()
        self.window.project_tab.refresh_sample_maps()
        self.window.project_tab.refresh_map_counts()
        self.window.project_state_manager.project_changed()

    def set_controls_enabled(self, enabled: bool) -> None:
        window = self.window
        was_visible = not window.elementSettingsPanel.isHidden()
        if was_visible == enabled:
            return
        splitter_sizes = window.splitter.sizes()
        window.elementSettingsPanel.setVisible(enabled)

        def finish_layout_change():
            if sum(splitter_sizes) > 0:
                window.splitter.setSizes(splitter_sizes)
            window.elementPlot.fit_image()

        timer = QtCore.QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(finish_layout_change)
        timer.timeout.connect(timer.deleteLater)
        timer.start(0)

    def update_normalizer(self) -> None:
        settings = self.current_element
        bins = 256
        if settings.normalizer == Normalizers.LOG:
            bins = np.geomspace(settings.minPositive, settings.dataRange[1], bins + 1)
            histogram_range = None
            data_domain = (settings.minPositive, settings.dataRange[1])
        else:
            histogram_range = (min(0, settings.dataRange[0]), settings.dataRange[1])
            data_domain = histogram_range
        histogram, edges = np.histogram(settings.data, bins=bins, range=histogram_range)
        self.window.elementHistogramPlot.set_histogram(
            histogram,
            edges,
            logarithmic=settings.normalizer == Normalizers.LOG,
            data_domain=data_domain,
            adaptive_binning=settings.normalizer != Normalizers.LOG,
        )
        self.window.gammaValue.setHidden(settings.normalizer != Normalizers.GAMMA)

    def _histogram_range_requested(self, minimum, maximum) -> None:
        settings = self.current_element
        if settings is None or settings.normalizer == Normalizers.LOG:
            return
        domain = (min(0, settings.dataRange[0]), settings.dataRange[1])
        histogram, edges = np.histogram(settings.data, bins=256, range=(minimum, maximum))
        self.window.elementHistogramPlot.set_histogram(
            histogram,
            edges,
            reset_view=False,
            data_domain=domain,
            adaptive_binning=True,
        )

    def update_plot(self) -> None:
        if self.current_element is None:
            return
        if self.window.image_controller.current_image is not None:
            self.window.image_controller.update_composed_image()
        else:
            self.display_current_element()

    def display_current_element(self, *, reset_view=False) -> None:
        if self.current_element is None:
            return
        self.window.image_controller.composer.coord_mapping = None
        self.window.elementPlot.set_image(
            self.current_element.transformedData(), reset_view=reset_view
        )

    def show_current_element(self) -> None:
        window = self.window
        settings = self.current_element
        self.set_controls_enabled(True)
        image = window.image_controller.current_image
        slot = window.imageElementButtonGroup.checkedId() if image is not None else -1
        is_image_element = image is not None and slot >= 0
        is_override = is_image_element and slot in image.element_overrides
        window.imageChannelNameLabel.setVisible(is_image_element)
        window.imageSettingsScopeCombo.setVisible(is_image_element)
        window.showSingleElementButton.setVisible(is_image_element)
        if is_image_element:
            key = image.channel_keys[slot]
            project_channel = window.project_data.project_channels.get(key)
            name = project_channel.name if project_channel is not None else settings.name
            window.imageChannelNameLabel.setText(f"{name}:")
            with QtCore.QSignalBlocker(window.imageSettingsScopeCombo):
                window.imageSettingsScopeCombo.setCurrentIndex(1 if is_override else 0)
        with QtCore.QSignalBlocker(window.elementNormalizer):
            window.elementNormalizer.setCurrentIndex(settings.normalizer.value)
        with QtCore.QSignalBlocker(window.elementName):
            window.elementName.setText(settings.name)
        with QtCore.QSignalBlocker(window.gammaValue):
            window.gammaValue.setValue(settings.gamma)
        lower_bound = 0 if settings.normalizer == Normalizers.LOG else min(0, settings.dataRange[0])
        for bound in range(2):
            with QtCore.QSignalBlocker(window.elementNormalizeRange[bound]):
                window.elementNormalizeRange[bound].setRange(lower_bound, settings.dataRange[1])
                window.elementNormalizeRange[bound].setValue(settings.trfRange[bound])

        self.update_normalizer()
        window.elementHistogramPlot.set_limits(*settings.trfRange)
        if image is None or window.showSingleElementButton.isChecked():
            self.display_current_element(reset_view=True)

    def edit_element(self, ref) -> None:
        self.current_element = self.window.project_data.element_settings[ref]
        self.window.image_controller.current_image = None
        with QtCore.QSignalBlocker(self.window.imageList):
            self.window.imageList.setCurrentRow(-1)
        self.window.image_controller.set_controls_enabled(False)
        try:
            self.show_current_element()
        except SourceUnavailableError as exc:
            self.clear_selection()
            self.window.show_source_unavailable(exc.source_id)

    def select_image_element(self, slot: int, *, reset_view=False) -> None:
        """Edit one image slot, or return to the composed image for ``-1``."""
        window = self.window
        image = window.image_controller.current_image
        if image is None:
            return
        settings = image.elements.get(slot)
        if settings is None:
            self.clear_selection()
            window.image_controller.update_composed_image(reset_view=reset_view)
            with QtCore.QSignalBlocker(window.imageElementButtonGroup):
                window.imageHeaderBox.edit.setChecked(True)
            return
        self._editing_channel_context = (
            None if slot in image.element_overrides else (image.sample_id, image.channel_keys[slot])
        )
        self.current_element = settings
        with QtCore.QSignalBlocker(window.elementList):
            if slot in image.element_overrides:
                window.elementList.setCurrentRow(-1)
            else:
                item = next(
                    (
                        window.elementList.item(row)
                        for row in range(window.elementList.count())
                        if window.elementList.item(row).data(ElementListWidget.ELEMENT_REF_ROLE)
                        == settings.ref
                    ),
                    None,
                )
                window.elementList.setCurrentItem(item)
        try:
            self.show_current_element()
        except SourceUnavailableError as exc:
            self.clear_selection()
            self.window.show_source_unavailable(exc.source_id)

    def clear_selection(self) -> None:
        self.current_element = None
        self._editing_channel_context = None
        self.set_controls_enabled(False)

    def _current_item_changed(self, current, _previous) -> None:
        if current is None:
            return
        ref = current.data(ElementListWidget.ELEMENT_REF_ROLE)
        key = current.data(ElementListWidget.CHANNEL_KEY_ROLE)
        sample = self.current_sample()
        self._editing_channel_context = (None if sample is None else sample.sample_id, key)
        try:
            self.ensure_settings(ref)
            self.edit_element(ref)
        except SourceUnavailableError as exc:
            self.clear_selection()
            self.window.show_source_unavailable(exc.source_id)

    def _mark_channel_settings_edited(self) -> None:
        settings = self.current_element
        if settings is None:
            return
        image = self.window.image_controller.current_image
        if image is not None:
            slot = self.window.imageElementButtonGroup.checkedId()
            if slot < 0 or slot in image.element_overrides:
                return
        if self._editing_channel_context is None:
            return
        sample_id, key = self._editing_channel_context
        became_selected = False
        if sample_id is None:
            channel = self.window.project_data.project_channels.get(key)
            if channel is None:
                _sample, local = self.window.project_data.channel_for_ref(settings.ref)
                self.window.project_data.add_project_channel(key, local.name, settings)
                became_selected = True
            else:
                channel.settings = settings
        else:
            became_selected = (
                self.window.project_data.sample_channel_state(sample_id, key)
                == SampleChannelState.SKIP
            )
            self.window.project_data.edit_channel(sample_id, key, settings=settings)
        if became_selected:
            self.refresh_current_channel_states()
            self.effective_channels_changed()

    def _name_changed(self) -> None:
        settings = self.current_element
        if settings is None:
            return
        window = self.window
        settings.name = window.elementName.text()
        if (
            window.image_controller.current_image is not None
            and window.imageElementButtonGroup.checkedId()
            in window.image_controller.current_image.element_overrides
        ):
            window.image_controller.update_composed_image()
            return
        if self._editing_channel_context is not None:
            sample_id, key = self._editing_channel_context
            if sample_id is None:
                if key not in window.project_data.project_channels:
                    window.project_data.add_project_channel(key, settings.name, settings)
                    self.effective_channels_changed()
                else:
                    window.project_data.rename_project_channel(key, settings.name)
                for sample in window.project_data.samples.values():
                    channel = sample.channels.get(key)
                    if channel is not None and channel.settings is not None:
                        channel.settings.name = settings.name
            else:
                was_skipped = (
                    window.project_data.sample_channel_state(sample_id, key)
                    == SampleChannelState.SKIP
                )
                window.project_data.edit_channel(
                    sample_id, key, name=settings.name, settings=settings
                )
                if was_skipped:
                    self.effective_channels_changed()
        self.refresh_display_names()
        if window.image_controller.current_image is not None:
            window.image_controller.update_composed_image()

    def _normalizer_changed(self) -> None:
        if self.current_element is None:
            return
        self.current_element.normalizer = Normalizers(self.window.elementNormalizer.currentIndex())
        self._mark_channel_settings_edited()
        self.update_normalizer()
        self.update_plot()

    def _gamma_changed(self) -> None:
        if self.current_element is None:
            return
        self.current_element.gamma = self.window.gammaValue.value()
        self._mark_channel_settings_edited()
        self.update_plot()

    def _range_changed(self, bound: int) -> None:
        if self.current_element is None:
            return
        field = self.window.elementNormalizeRange[bound]
        self.current_element.setMinmax(bound, field.value())
        self._mark_channel_settings_edited()
        field.setValue(self.current_element.trfRange[bound])
        self.window.elementHistogramPlot.set_limits(*self.current_element.trfRange)
        self.update_plot()

    def _set_range_by_mode(self, mode: str) -> None:
        if self.current_element is None:
            return
        self.current_element.setMinmaxByMode(mode)
        self._mark_channel_settings_edited()
        for field, value in zip(
            self.window.elementNormalizeRange, self.current_element.trfRange, strict=True
        ):
            field.setValue(value)
        self.update_plot()

    def _histogram_limits_changed(self, minimum, maximum) -> None:
        if self.current_element is None:
            return
        self.current_element.trfRange[:] = [minimum, maximum]
        self._mark_channel_settings_edited()
        for field, value in zip(
            self.window.elementNormalizeRange, self.current_element.trfRange, strict=True
        ):
            with QtCore.QSignalBlocker(field):
                field.setValue(value)
        self.update_plot()

    def source_alias_for_ref(self, ref: ElementRef):
        asset = self.window.project_data.assets.get(ref.source_id)
        if asset is not None:
            return self.window.project_data.samples[asset.sample_id].name
        return ref.source_id

    def element_display_name(self, ref: ElementRef, *, force_alias=False):
        settings = self.window.project_data.element_settings[ref]
        label = settings.name
        if force_alias or len(self.window.project_data.samples) > 1:
            label = f"{label} ({self.source_alias_for_ref(ref)})"
        source = self.window.project_data.sources.get(ref.source_id)
        if source is not None and not source.is_open:
            label += " [closed]"
        return label

    def element_local_display_name(self, ref):
        source = self.window.project_data.sources.get(ref.source_id)
        original = (
            source.default_element_name(ref)
            if source is not None
            else ref.item_id.rsplit("/", 1).pop()
        )
        settings = self.window.project_data.element_settings.get(ref)
        if settings is not None and settings.name != original:
            return f"{settings.name} ({original})"
        return original

    def refresh_display_names(self) -> None:
        window = self.window
        sample = self.current_sample()
        with QtCore.QSignalBlocker(window.elementList):
            for row in range(window.elementList.count()):
                item = window.elementList.item(row)
                key = item.data(ElementListWidget.CHANNEL_KEY_ROLE)
                ref = item.data(ElementListWidget.ELEMENT_REF_ROLE)
                if sample is None:
                    project_channel = window.project_data.project_channels.get(key)
                    name = (
                        window.project_data.element_settings[ref].name
                        if project_channel is None
                        else project_channel.name
                    )
                else:
                    state = window.project_data.sample_channel_state(sample.sample_id, key)
                    if state == SampleChannelState.INHERIT:
                        name = window.project_data.project_channels[key].name
                    elif state == SampleChannelState.OVERRIDE:
                        override = sample.channel_overrides[key]
                        name = override.name or sample.channels[key].name
                    else:
                        name = sample.channels[key].name
                item.setText(self.channel_list_label(key, name))
        window.analysis_controller.update_channels()
        window.analysis_controller.update_elements()

        for box in window.imageElementBoxes:
            combo = box.combo
            current = combo.currentData()
            for row in range(1, combo.count()):
                ref = combo.itemData(row)
                if ref in window.project_data.element_settings:
                    combo.setItemText(row, window.project_data.element_settings[ref].name)
            if current is not None:
                index = window.image_controller.combo_index_for_data(combo, current)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def clear_project(self) -> None:
        self.current_element = None
        self._editing_channel_context = None
        self._settings_failures.clear()
        self.window.elementList.clear()
        self.set_controls_enabled(False)

    def discard_settings_failures(self, refs) -> None:
        for ref in refs:
            self._settings_failures.pop(ref, None)

    def has_settings_failure(self, ref) -> bool:
        return ref in self._settings_failures

    def discard_source_failures(self, source_id) -> None:
        for ref in list(self._settings_failures):
            if ref.source_id == source_id:
                self._settings_failures.pop(ref)
