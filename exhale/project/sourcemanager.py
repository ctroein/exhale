"""Source-file import, removal, closure, and relocation policy."""

from __future__ import annotations

import traceback

from ..data.projectdata import DuplicateChannelError
from ..data.source_refs import open_source
from ..overridecursor import OverrideCursor


class SourceManager:
    """Coordinate source lifecycle operations and their dependent UI refreshes."""

    def __init__(self, window):
        self.window = window

    def select_and_open_files(self) -> None:
        """Ask for source files and add the selected files to the project."""
        filenames = self.select_file_names("Add files to project")
        if filenames:
            with OverrideCursor():
                self.open_files(filenames)

    def select_file_names(self, title):
        """Return source filenames selected in the shared file dialog."""
        filters = [
            "Image files (*.h5 *.hdf *.hdf5 *.tif *.tiff)",
            "HDF5 files (*.h5 *.hdf *.hdf5)",
            "TIFF files (*.tif *.tiff)",
            "All files (*)",
        ]
        return self.window.askFileName(
            title=title,
            filter=";;".join(filters),
            settingname="OpenDir",
            multiple=True,
        )

    def open_files(self, filenames, *, sample_id=None, asset_ids=None) -> None:
        """Open files, grouping a project-level TIFF batch into one sample."""
        window = self.window
        last_sample_id = None
        tiff_sample_id = sample_id

        for filename in filenames:
            try:
                source = open_source(filename)
            except Exception:
                window.show_error(
                    "The file could not be opened.",
                    f"File: {filename}\n\n{traceback.format_exc()}",
                )
                continue
            if asset_ids is not None and filename in asset_ids:
                source.source_id = asset_ids[filename]
            source_id = source.source_id

            if (
                source_id in window.project_data.sources
                and window.project_data.sources[source_id].is_open
            ):
                source.close()
                print("Warning: opened already opened file", source_id)
                last_sample_id = window.project_data.assets[source_id].sample_id
                continue

            try:
                target_sample_id = sample_id
                if target_sample_id is None and source.kind == "tiff":
                    target_sample_id = tiff_sample_id
                existing_sample_ids = set(window.project_data.samples)
                sample = window.project_data.register_source(source, sample_id=target_sample_id)
            except DuplicateChannelError as exc:
                source.close()
                window.show_error(
                    "The file could not be added because the sample already contains "
                    "an element map with the same channel key.",
                    f"File: {filename}\nSample: {exc.sample_name}\n"
                    f"Channel key: {exc.channel_key}\n\n{traceback.format_exc()}",
                )
                continue
            except Exception as exc:
                source.close()
                if source.kind == "tiff":
                    window.show_tiff_read_error(filename, exc)
                else:
                    window.show_error(
                        "The file could not be added to the sample.",
                        f"File: {filename}\n\n{traceback.format_exc()}",
                    )
                continue
            if source.kind == "tiff":
                for channel in sample.channels.values():
                    if channel.ref.source_id != source_id:
                        continue
                    if channel.key not in window.project_data.project_channels:
                        window.project_data.add_project_channel(
                            channel.key, channel.name, channel.settings
                        )
                try:
                    for channel in sample.channels.values():
                        if channel.ref is not None and channel.ref.source_id == source_id:
                            window.element_controller.ensure_settings(channel.ref)
                except Exception as exc:
                    window.project_data.remove_asset(source_id)
                    if sample.sample_id not in existing_sample_ids and not sample.asset_ids:
                        window.project_data.samples.pop(sample.sample_id, None)
                    window.show_tiff_read_error(filename, exc)
                    continue
                if tiff_sample_id is None:
                    tiff_sample_id = sample.sample_id
            last_sample_id = sample.sample_id

        if last_sample_id is not None:
            window.element_controller.effective_channels_changed()
            window.element_controller.refresh_sample_selector(last_sample_id)
            if hasattr(window, "project_state_manager"):
                window.project_state_manager.project_changed()

    def remove_project_asset(self, asset_id) -> None:
        """Remove one asset and discard its dependent image references."""
        window = self.window
        asset = window.project_data.assets[asset_id]
        sample_id = asset.sample_id
        refs = {
            channel.ref
            for channel in window.project_data.samples[sample_id].channels.values()
            if channel.ref is not None and channel.ref.source_id == asset_id
        }
        window.project_data.remove_asset(asset_id)
        window.element_controller.discard_settings_failures(refs)
        window.image_controller.remove_asset_references(asset_id, refs)
        self._after_project_data_removed(sample_id)

    def remove_project_sample(self, sample_id) -> None:
        """Remove one sample and all image state which refers to it."""
        window = self.window
        refs = {
            channel.ref
            for channel in window.project_data.samples[sample_id].channels.values()
            if channel.ref is not None
        }
        window.project_data.remove_sample(sample_id)
        window.element_controller.discard_settings_failures(refs)
        window.image_controller.remove_sample_images(sample_id)
        self._after_project_data_removed(None)

    def replace_project_asset_path(self, asset_id, filename) -> bool:
        """Relocate one asset while retaining its project identity."""
        window = self.window
        try:
            with OverrideCursor():
                window.project_data.replace_asset_path(asset_id, filename)
        except Exception as exc:
            window.show_error("Replacing file failed", str(exc))
            return False
        window.element_controller.discard_source_failures(asset_id)
        window.element_controller.effective_channels_changed()
        window.project_data.update_external_data_root(window.project_dir)
        window.element_controller.refresh_sample_selector(
            window.project_data.assets[asset_id].sample_id
        )
        if window.image_controller.current_image is not None:
            window.image_controller.update_composed_image()
        window.project_state_manager.project_changed()
        return True

    def replace_external_data_root(self, directory) -> None:
        """Relocate available assets beneath a replacement data directory."""
        window = self.window
        with OverrideCursor():
            failures = window.project_data.replace_external_data_root(directory)
        if failures:
            details = "\n".join(f"{asset_id}: {error}" for asset_id, error in failures.items())
            window.show_error("Replacing data directory failed", details)
        window.project_data.update_external_data_root(window.project_dir)
        window.element_controller.refresh_sample_selector(window.loadedFileComboBox.currentData())
        window.project_tab.refresh()
        if window.image_controller.current_image is not None:
            window.image_controller.update_composed_image()
        if len(failures) < len(window.project_data.assets):
            window.project_state_manager.project_changed()

    def _after_project_data_removed(self, selected_sample_id) -> None:
        window = self.window
        window.element_controller.effective_channels_changed()
        window.element_controller.refresh_sample_selector(selected_sample_id)
        window.project_tab.refresh(selected_sample_id)
        if hasattr(window, "project_state_manager"):
            window.project_state_manager.project_changed()

    def close_source_handles(self) -> None:
        """Close source handles while discarding or shutting down a project."""
        for source in self.window.project_data.sources.values():
            if source.is_open:
                source.close()
