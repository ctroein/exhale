"""Controller for correlation calculation, caching, and result presentation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import numpy as np
from pyqtgraph.exporters import ImageExporter, SVGExporter
from qtpy import QtCore, QtWidgets

from ..data.plotsettings import ELEMENT_CORRELATIONS, SAMPLE_SIMILARITIES
from ..tooltips import CORRELATION_MATRIX
from .correlations import (
    CorrelationMatrix,
    SampleSimilarityMatrix,
    correlation_matrix,
    density_grid,
)
from .correlations import sample_similarity_matrix as calculate_sample_similarities
from .correlationwidgets import CorrelationMatrixView, CorrelationPlotWidget


@dataclass(frozen=True)
class _ElementCacheEntry:
    signature: tuple
    result: CorrelationMatrix


class CorrelationController:
    """Own the three independent correlation analyses and their session caches."""

    ELEMENT_MODE = "elements"
    SCATTER_MODE = "scatter"
    SAMPLE_MODE = "samples"
    SAMPLE_ID_ROLE = QtCore.Qt.UserRole

    def __init__(self, window):
        self.window = window
        self._element_cache: dict[tuple[str, tuple[str, ...]], _ElementCacheEntry] = {}
        self._similarity_cache: dict[tuple, SampleSimilarityMatrix] = {}
        self.element_matrix = CorrelationMatrixView(
            window.elementCorrelationPlotHost,
            window.showElementCorrelationValues,
            window.elementCorrelationDecimals,
            window.elementCorrelationDecimalsLabel,
            window.copyElementCorrelationTable,
            window.elementCorrelationPalette,
            window.project_data.matrix_plot_settings[ELEMENT_CORRELATIONS],
        )
        self.element_matrix.plot.matrix_plot.setToolTip(CORRELATION_MATRIX)
        self.scatter_plot = self._install_plot(window.elementScatterPlotHost)
        self.similarity_matrix = CorrelationMatrixView(
            window.sampleSimilarityPlotHost,
            window.showSampleSimilarityValues,
            window.sampleSimilarityDecimals,
            window.sampleSimilarityDecimalsLabel,
            window.copySampleSimilarityTable,
            window.sampleSimilarityPalette,
            window.project_data.matrix_plot_settings[SAMPLE_SIMILARITIES],
        )

        excluded_header = window.sampleSimilarityExcluded.header()
        excluded_header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        excluded_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)

    @staticmethod
    def _install_plot(host):
        plot = CorrelationPlotWidget(host)
        plot_layout = QtWidgets.QVBoxLayout(host)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(plot)
        return plot

    def setup(self) -> None:
        window = self.window
        window.calculateSampleSimilarities.hide()
        window.correlationModes.currentChanged.connect(self._analysis_tab_changed)
        window.tabWidget.currentChanged.connect(self._main_tab_changed)
        window.elementCorrelationSample.currentIndexChanged.connect(self._element_sample_changed)
        window.elementScatterSample.currentIndexChanged.connect(self._scatter_sample_changed)
        window.elementScatterX.currentIndexChanged.connect(self._update_scatter)
        window.elementScatterY.currentIndexChanged.connect(self._update_scatter)
        window.elementScatterPresentation.currentIndexChanged.connect(
            self._scatter_presentation_changed
        )
        window.elementScatterBins.valueChanged.connect(self._update_scatter)
        window.sampleSimilaritySamples.itemSelectionChanged.connect(self._sample_selection_changed)
        window.saveElementCorrelationPlot.clicked.connect(
            partial(self.save_plot, self.element_matrix.plot, "element-correlations.png")
        )
        window.saveElementScatterPlot.clicked.connect(
            partial(self.save_plot, self.scatter_plot, "element-scatter.png")
        )
        window.saveSampleSimilarityPlot.clicked.connect(
            partial(self.save_plot, self.similarity_matrix.plot, "sample-similarities.png")
        )
        self.element_matrix.pairActivated.connect(self._show_pair)
        window.channelsChanged.connect(self.refresh_samples)
        self._scatter_presentation_changed(update=False)
        self.refresh_samples()

    def clear_project(self) -> None:
        self._element_cache.clear()
        self._similarity_cache.clear()
        self.element_matrix.set_result(None)
        self.similarity_matrix.set_result(None)
        self.element_matrix.reload_settings()
        self.similarity_matrix.reload_settings()
        self.scatter_plot.clear_scatter()
        self.window.elementCorrelationStatus.clear()
        self.window.elementScatterStatus.clear()
        self.window.sampleSimilarityStatus.clear()
        self.refresh_samples()

    def reload_appearance(self) -> None:
        self.element_matrix.reload_appearance()
        self.scatter_plot.reload_appearance()
        self.similarity_matrix.reload_appearance()

    def refresh_samples(self) -> None:
        """Refresh each analysis' sample choices without coupling their selections."""
        window = self.window
        self.element_matrix.reload_settings()
        self.similarity_matrix.reload_settings()
        selected_element_sample = window.elementCorrelationSample.currentData()
        selected_scatter_sample = window.elementScatterSample.currentData()
        selected_similarity_ids = {
            item.data(self.SAMPLE_ID_ROLE)
            for item in window.sampleSimilaritySamples.selectedItems()
        }
        had_similarity_items = window.sampleSimilaritySamples.count() > 0
        samples = list(window.project_data.samples.values())

        for combo, selected in (
            (window.elementCorrelationSample, selected_element_sample),
            (window.elementScatterSample, selected_scatter_sample),
        ):
            with QtCore.QSignalBlocker(combo):
                combo.clear()
                for sample in samples:
                    combo.addItem(sample.name, sample.sample_id)
                index = combo.findData(selected)
                combo.setCurrentIndex(index if index >= 0 else (0 if samples else -1))

        with QtCore.QSignalBlocker(window.sampleSimilaritySamples):
            window.sampleSimilaritySamples.clear()
            for sample in samples:
                item = QtWidgets.QListWidgetItem(sample.name, window.sampleSimilaritySamples)
                item.setData(self.SAMPLE_ID_ROLE, sample.sample_id)
                item.setSelected(
                    sample.sample_id in selected_similarity_ids or not had_similarity_items
                )
        self._sample_selection_changed(recalculate=False)
        self._refresh_scatter_elements()
        self._update_current_if_visible()

    def _correlations_visible(self) -> bool:
        return self.window.tabWidget.currentWidget() is self.window.correlationsTab

    def _main_tab_changed(self) -> None:
        self._update_current_if_visible()

    def _update_current_if_visible(self) -> None:
        if self._correlations_visible():
            self._analysis_tab_changed()

    def _analysis_tab_changed(self) -> None:
        if not self._correlations_visible():
            return
        current = self.window.correlationModes.currentWidget()
        if current is self.window.elementCorrelationTab:
            self.calculate_elements(show_errors=False)
        elif current is self.window.elementScatterTab:
            self._update_scatter()
        elif current is self.window.sampleSimilarityTab:
            self.calculate_samples(show_errors=False)

    def _element_sample_changed(self) -> None:
        if (
            self._correlations_visible()
            and self.window.correlationModes.currentWidget() is self.window.elementCorrelationTab
        ):
            self.calculate_elements(show_errors=False)

    def _scatter_sample_changed(self) -> None:
        self._refresh_scatter_elements()
        if self._correlations_visible():
            self._update_scatter()

    def _scatter_presentation_changed(self, _index=None, *, update=True) -> None:
        density = self.window.elementScatterPresentation.currentIndex() == 1
        self.window.elementScatterBins.setEnabled(density)
        self.window.elementScatterBinsLabel.setEnabled(density)
        self.window.elementScatterSamplingWarning.setVisible(not density)
        if update:
            self._update_scatter()

    def _refresh_scatter_elements(self) -> None:
        sample = self.window.project_data.samples.get(
            self.window.elementScatterSample.currentData()
        )
        channels = (
            sorted(
                self._effective_channels(sample).values(),
                key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
            )
            if sample is not None
            else []
        )
        combos = (self.window.elementScatterX, self.window.elementScatterY)
        previous = tuple(combo.currentData() for combo in combos)
        for combo_index, combo in enumerate(combos):
            with QtCore.QSignalBlocker(combo):
                combo.clear()
                for channel in channels:
                    combo.addItem(channel.name, channel.key)
                index = combo.findData(previous[combo_index])
                if index < 0 and channels:
                    index = min(combo_index, len(channels) - 1)
                combo.setCurrentIndex(index)

    def _selected_similarity_samples(self):
        project_data = self.window.project_data
        return [
            project_data.samples[item.data(self.SAMPLE_ID_ROLE)]
            for item in self.window.sampleSimilaritySamples.selectedItems()
            if item.data(self.SAMPLE_ID_ROLE) in project_data.samples
        ]

    def _effective_channels(self, sample):
        return {
            key: channel
            for key, channel in sample.effective_channels(
                self.window.project_data.project_channels
            ).items()
            if channel.available
        }

    def _common_keys(self, samples) -> tuple[str, ...]:
        if not samples:
            return ()
        key_sets = [set(self._effective_channels(sample)) for sample in samples]
        return tuple(sorted(set.intersection(*key_sets), key=str.casefold))

    def _sample_selection_changed(self, *, recalculate=True) -> None:
        samples = self._selected_similarity_samples()
        common = self._common_keys(samples)
        effective = [self._effective_channels(sample) for sample in samples]
        all_keys = {key for channels in effective for key in channels}
        excluded_keys = sorted(all_keys - set(common), key=str.casefold)
        self.window.sampleSimilaritySummary.setText(
            f"{len(common)} common elements; {len(excluded_keys)} excluded"
            if samples
            else "Select at least two samples"
        )
        excluded_list = self.window.sampleSimilarityExcluded
        excluded_list.clear()
        project_channels = self.window.project_data.project_channels
        for key in excluded_keys:
            name = project_channels[key].name if key in project_channels else key
            available_count = sum(key in channels for channels in effective)
            QtWidgets.QTreeWidgetItem(excluded_list, (name, f"{available_count}/{len(samples)}"))
        if (
            recalculate
            and self._correlations_visible()
            and self.window.correlationModes.currentWidget() is self.window.sampleSimilarityTab
        ):
            self.calculate_samples(show_errors=False)

    def _channel_arrays(self, sample, keys: tuple[str, ...]):
        arrays = []
        for key in keys:
            channel = sample.channels[key]
            if channel.data_source is None:
                raise RuntimeError(f"Element {key!r} has no available source data")
            arrays.append(channel.data_source.array())
        return tuple(arrays)

    def _element_result(
        self, sample, keys: tuple[str, ...], labels: tuple[str, ...]
    ) -> CorrelationMatrix:
        effective = self._effective_channels(sample)
        signature = tuple(
            (key, effective[key].ref, effective[key].name, id(sample.channels[key].data_source))
            for key in keys
        )
        cache_key = (sample.sample_id, keys)
        cached = self._element_cache.get(cache_key)
        if cached is not None and cached.signature == signature:
            return cached.result
        result = correlation_matrix(self._channel_arrays(sample, keys), labels, keys)
        self._element_cache[cache_key] = _ElementCacheEntry(signature, result)
        return result

    def calculate_elements(self, *, show_errors=True) -> None:
        sample = self.window.project_data.samples.get(
            self.window.elementCorrelationSample.currentData()
        )
        if sample is None:
            self._element_calculation_failed("Select a sample first.", show_errors)
            return
        channels = sorted(
            self._effective_channels(sample).values(),
            key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
        )
        if len(channels) < 2:
            self._element_calculation_failed(
                "At least two selected and available elements are required.", show_errors
            )
            return
        keys = tuple(channel.key for channel in channels)
        labels = tuple(channel.name for channel in channels)
        try:
            result = self._element_result(sample, keys, labels)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self._element_calculation_failed(str(error), show_errors)
            return
        counts = result.counts[np.triu_indices(len(keys), 1)]
        self.element_matrix.set_result(result)
        self.window.elementCorrelationStatus.setText(
            f"{len(keys)} elements; {int(counts.min())}–{int(counts.max())} paired pixels"
        )

    def _element_calculation_failed(self, message: str, show_error: bool) -> None:
        self.element_matrix.set_result(None)
        self.window.elementCorrelationStatus.setText(message)
        if show_error:
            self._show_input_error(message)

    def calculate_samples(self, *, show_errors=True) -> None:
        samples = self._selected_similarity_samples()
        if len(samples) < 2:
            self._sample_calculation_failed("Select at least two samples.", show_errors)
            return
        keys = self._common_keys(samples)
        if len(keys) < 3:
            self._sample_calculation_failed(
                "At least three selected and available elements common to every sample are required.",
                show_errors,
            )
            return
        project_channels = self.window.project_data.project_channels
        first_effective = self._effective_channels(samples[0])
        labels = tuple(
            project_channels[key].name if key in project_channels else first_effective[key].name
            for key in keys
        )
        signature = tuple(
            (
                sample.sample_id,
                sample.name,
                tuple(
                    (
                        key,
                        self._effective_channels(sample)[key].ref,
                        id(sample.channels[key].data_source),
                    )
                    for key in keys
                ),
            )
            for sample in samples
        )
        try:
            result = self._similarity_cache.get(signature)
            if result is None:
                matrices = tuple(self._element_result(sample, keys, labels) for sample in samples)
                result = calculate_sample_similarities(
                    matrices,
                    tuple(sample.name for sample in samples),
                    tuple(sample.sample_id for sample in samples),
                )
                self._similarity_cache[signature] = result
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self._sample_calculation_failed(str(error), show_errors)
            return
        self.similarity_matrix.set_result(result)
        self.window.sampleSimilarityStatus.setText(
            f"{len(samples)} samples; {len(keys)} common elements; "
            f"{len(result.feature_labels)} fingerprint entries"
        )

    def _sample_calculation_failed(self, message: str, show_error: bool) -> None:
        self.similarity_matrix.set_result(None)
        self.window.sampleSimilarityStatus.setText(message)
        if show_error:
            self._show_input_error(message)

    def _update_scatter(self) -> None:
        if self.window.correlationModes.currentWidget() is not self.window.elementScatterTab:
            return
        if not self._correlations_visible():
            return
        sample = self.window.project_data.samples.get(
            self.window.elementScatterSample.currentData()
        )
        if sample is None:
            self.scatter_plot.clear_scatter()
            self.window.elementScatterStatus.setText("Select a sample first.")
            return
        effective = self._effective_channels(sample)
        first_key = self.window.elementScatterX.currentData()
        second_key = self.window.elementScatterY.currentData()
        if first_key not in effective or second_key not in effective:
            self.scatter_plot.clear_scatter()
            self.window.elementScatterStatus.setText("Select two available elements.")
            return
        first_channel = effective[first_key]
        second_channel = effective[second_key]
        try:
            first, second = self._channel_arrays(sample, (first_key, second_key))
            result = correlation_matrix(
                (first, second),
                (first_channel.name, second_channel.name),
                (first_key, second_key),
            )
            density = (
                density_grid(first, second, bins=self.window.elementScatterBins.value())
                if self.window.elementScatterPresentation.currentIndex() == 1
                else None
            )
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self.scatter_plot.clear_scatter()
            self.window.elementScatterStatus.setText(str(error))
            return
        if density is not None:
            self.scatter_plot.show_density(density, first_channel.name, second_channel.name)
        else:
            self.scatter_plot.show_scatter(first, second, first_channel.name, second_channel.name)
        value = result.values[0, 1]
        count = result.counts[0, 1]
        value_text = "undefined" if not np.isfinite(value) else f"{value:.6g}"
        self.window.elementScatterStatus.setText(
            f"Pearson correlation: {value_text}; {count} paired pixels"
        )

    def _show_pair(self, row: int, column: int) -> None:
        result = self.element_matrix.result
        if (
            result is None
            or row == column
            or not (0 <= row < len(result.keys))
            or not (0 <= column < len(result.keys))
        ):
            return
        sample_id = self.window.elementCorrelationSample.currentData()
        with QtCore.QSignalBlocker(self.window.elementScatterSample):
            self.window.elementScatterSample.setCurrentIndex(
                self.window.elementScatterSample.findData(sample_id)
            )
        self._refresh_scatter_elements()
        self.window.elementScatterX.setCurrentIndex(
            self.window.elementScatterX.findData(result.keys[column])
        )
        self.window.elementScatterY.setCurrentIndex(
            self.window.elementScatterY.findData(result.keys[row])
        )
        self.window.correlationModes.setCurrentWidget(self.window.elementScatterTab)

    def save_plot(self, plot, default_filename: str) -> None:
        project_dir = self.window.project_dir
        filename = self.window.askFileName(
            "Save correlation plot",
            filter="PNG image (*.png);;SVG image (*.svg)",
            settingname="correlations/export_directory",
            save=True,
            directory=None if project_dir is None else str(project_dir),
            defaultfilename=default_filename,
        )
        if filename is None:
            return
        try:
            exporter_class = SVGExporter if filename.lower().endswith(".svg") else ImageExporter
            exporter_class(plot.current_plot_item()).export(filename)
        except (OSError, RuntimeError, ValueError) as error:
            self._show_input_error(f"The plot could not be saved.\n\n{error}")

    def copy_table(self, mode=ELEMENT_MODE) -> None:
        matrix = self.element_matrix if mode == self.ELEMENT_MODE else self.similarity_matrix
        matrix.copy_table()

    def _show_input_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(
            self.window, "Cannot calculate correlations", message, QtWidgets.QMessageBox.Ok
        )
