"""Project-owned samples, files, and channel organization."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .elementsettings import ElementSettingsDefaults
from .imagesettings import ImageSettings
from .plotsettings import MATRIX_PLOT_KEYS, MatrixPlotSettings
from .source_refs import ElementRef, LoadedSource
from .tiffimport import infer_tiff_import


class DuplicateChannelError(ValueError):
    """A source channel key is already present in its target sample."""

    def __init__(self, sample_name: str, channel_key: str):
        self.sample_name = sample_name
        self.channel_key = channel_key
        super().__init__(f"Sample {sample_name!r} already has channel {channel_key!r}")


def shortest_unique_path_suffixes(paths):
    """Return the shortest component-wise suffix distinguishing each path."""
    paths = [str(path) for path in paths]
    parts = {path: Path(path).parts for path in paths}
    result = {}
    for path in paths:
        own = parts[path]
        for count in range(1, len(own) + 1):
            suffix = own[-count:]
            if all(other == path or parts[other][-count:] != suffix for other in paths):
                break
        result[path] = str(Path(*suffix))
    return result


@dataclass
class DataAsset:
    """A physical file retained by the project."""

    asset_id: str
    path: str
    source: LoadedSource
    sample_id: str
    original_path: str | None = None

    @property
    def is_available(self) -> bool:
        return self.source.is_open


@dataclass
class Channel:
    """A named channel, optionally backed by data in a sample."""

    key: str
    name: str
    ref: ElementRef | None = None
    settings: Any = None
    data_source: Any = None

    def __post_init__(self):
        if not self.key:
            raise ValueError("Channel key must not be empty")

    @property
    def is_available(self) -> bool:
        if self.data_source is None:
            return False
        source = getattr(self.data_source, "source", None)
        return source.is_open if source is not None else self.data_source.is_available


@dataclass
class ChannelOverride:
    """Sample-local changes to an inherited or local channel."""

    name: str | None = None
    settings: Any = None


class SampleChannelState(Enum):
    """How a sample uses one of its available channels."""

    SKIP = "skip"
    INHERIT = "inherit"
    OVERRIDE = "override"


@dataclass(frozen=True)
class ResolvedChannel:
    """The effective channel presented for one sample."""

    key: str
    name: str
    ref: ElementRef
    settings: Any
    overridden: bool
    available: bool


@dataclass(frozen=True)
class SegmentationParameters:
    """Parameters used to produce one segmentation result."""

    nuclei_expansion: int
    nuclei_min_area: int
    cluster_min_k: int
    cluster_max_k: int


@dataclass
class SegmentationResult:
    """The most recent successful segmentation run for one sample."""

    sample_id: str
    nuclei_ref: ElementRef
    tissue_ref: ElementRef
    element_refs: tuple[ElementRef, ...]
    parameters: SegmentationParameters
    xrf_sample: Any


@dataclass
class Sample:
    """A group of compatible channel maps used together."""

    sample_id: str
    name: str
    asset_ids: list[str] = field(default_factory=list)
    channels: dict[str, Channel] = field(default_factory=dict)
    # Missing key: inherit a project channel. None: explicitly skip it.
    channel_overrides: dict[str, ChannelOverride | None] = field(default_factory=dict)
    shape: tuple[int, int] | None = None

    @staticmethod
    def _channel_shape(channel: Channel) -> tuple[int, int]:
        if channel.data_source is None:
            raise ValueError(f"Channel {channel.key!r} has no data")
        shape = tuple(channel.data_source.shape)
        if len(shape) != 2 or not all(shape):
            raise ValueError(f"Channel {channel.key!r} must be a nonempty 2-D map")
        return shape

    def replace_asset_channels(self, asset_id: str, channels: list[Channel]) -> None:
        """Atomically add or replace all channels supplied by one asset."""
        remaining = {
            key: channel
            for key, channel in self.channels.items()
            if channel.ref is None or channel.ref.source_id != asset_id
        }
        expected_shape = None
        if remaining:
            expected_shape = self._channel_shape(next(iter(remaining.values())))
        additions = {}
        for channel in channels:
            if channel.key in remaining or channel.key in additions:
                raise DuplicateChannelError(self.name, channel.key)
            shape = self._channel_shape(channel)
            if expected_shape is None:
                expected_shape = shape
            elif shape != expected_shape:
                raise ValueError(
                    f"Channel {channel.key!r} has shape {shape}; sample "
                    f"{self.name!r} uses {expected_shape}"
                )
            additions[channel.key] = channel
        self.channels = remaining | additions
        self.shape = expected_shape

    def remove_asset_channels(self, asset_id: str) -> list[Channel]:
        """Remove and return channels backed by one asset."""
        removed = [
            channel
            for channel in self.channels.values()
            if channel.ref is not None and channel.ref.source_id == asset_id
        ]
        self.channels = {
            key: channel for key, channel in self.channels.items() if channel not in removed
        }
        self.asset_ids = [value for value in self.asset_ids if value != asset_id]
        self.shape = (
            self._channel_shape(next(iter(self.channels.values()))) if self.channels else None
        )
        return removed

    def rename_channel(self, old_key: str, new_key: str, name: str | None = None) -> None:
        if old_key not in self.channels:
            raise KeyError(old_key)
        if new_key != old_key and new_key in self.channels:
            raise ValueError(f"Channel {new_key!r} already exists")
        channel = self.channels.pop(old_key)
        channel.key = new_key
        if name is not None:
            channel.name = name
        self.channels[new_key] = channel
        if old_key in self.channel_overrides:
            self.channel_overrides[new_key] = self.channel_overrides.pop(old_key)

    def effective_channels(
        self, project_channels: dict[str, Channel]
    ) -> dict[str, ResolvedChannel]:
        """Resolve project selection and this sample's differences."""
        effective = {}
        keys = project_channels.keys() | self.channel_overrides.keys()
        for key in keys:
            local_channel = self.channels.get(key)
            if local_channel is None or local_channel.ref is None:
                continue

            if key in self.channel_overrides:
                override = self.channel_overrides[key]
                if override is None:
                    continue
                overridden = True
            else:
                override = None
                overridden = False

            project_channel = project_channels.get(key)
            if project_channel is None and not overridden:
                continue

            default_name = (
                project_channel.name if project_channel is not None else local_channel.name
            )
            default_settings = (
                local_channel.settings
                if local_channel.settings is not None
                else (project_channel.settings if project_channel is not None else None)
            )
            effective[key] = ResolvedChannel(
                key=key,
                name=(
                    override.name
                    if override is not None and override.name is not None
                    else default_name
                ),
                ref=local_channel.ref,
                settings=(
                    override.settings
                    if override is not None and override.settings is not None
                    else default_settings
                ),
                overridden=overridden,
                available=local_channel.is_available,
            )
        return effective


class ProjectData:
    """Own assets, samples, images, shared choices, defaults, and derived results."""

    def __init__(self, element_defaults=None):
        self.element_defaults = (
            ElementSettingsDefaults() if element_defaults is None else element_defaults.copy()
        )
        self.image_defaults = ImageSettings("")
        self.assets: dict[str, DataAsset] = {}
        self.samples: dict[str, Sample] = {}
        self.project_channels: dict[str, Channel] = {}
        self.images: dict[int, ImageSettings] = {}
        self.segmentation_results: dict[str, SegmentationResult] = {}
        self.matrix_plot_settings = {key: MatrixPlotSettings() for key in MATRIX_PLOT_KEYS}
        self.external_data_root: str | None = None

        self.element_settings: dict[ElementRef, Any] = {}

    @property
    def sources(self) -> dict[str, LoadedSource]:
        """Return sources indexed by their stable asset identity."""
        return {asset_id: asset.source for asset_id, asset in self.assets.items()}

    def create_sample(self, name: str, sample_id: str | None = None):
        """Create and register an empty sample with a stable identity."""

        sample_id = sample_id or str(uuid4())
        if sample_id in self.samples:
            raise ValueError(f"Sample {sample_id!r} already exists")
        sample = Sample(sample_id=sample_id, name=name)
        self.samples[sample_id] = sample
        return sample

    def rename_sample(self, sample_id: str, name: str) -> None:
        if not name:
            raise ValueError("Sample name must not be empty")
        self.samples[sample_id].name = name

    def add_project_channel(self, key: str, name: str | None = None, settings=None) -> Channel:
        """Add a channel to the selection inherited by samples."""
        if not key:
            raise ValueError("Channel key must not be empty")
        channel = self.project_channels.get(key)
        if channel is None:
            channel = Channel(key=key, name=name or key, settings=settings)
            self.project_channels[key] = channel
        else:
            if name is not None:
                channel.name = name
            if settings is not None:
                channel.settings = settings
        return channel

    def add_project_channel_from_sample(self, sample_id: str, key: str) -> Channel:
        local = self.samples[sample_id].channels[key]
        return self.add_project_channel(key, name=local.name, settings=local.settings)

    def remove_project_channel(self, key: str) -> None:
        """Remove a project default without deleting local overrides."""
        self.project_channels.pop(key, None)

    def rename_project_channel(self, key: str, name: str) -> None:
        if not name:
            raise ValueError("Channel name must not be empty")
        self.project_channels[key].name = name

    def sample_channel_state(self, sample_id: str, key: str) -> SampleChannelState:
        """Return whether a sample skips, inherits, or overrides a channel."""

        sample = self.samples[sample_id]
        if key in sample.channel_overrides:
            return (
                SampleChannelState.SKIP
                if sample.channel_overrides[key] is None
                else SampleChannelState.OVERRIDE
            )
        if key in self.project_channels:
            return SampleChannelState.INHERIT
        return SampleChannelState.SKIP

    def inherit_sample_channel(self, sample_id: str, key: str) -> None:
        sample = self.samples[sample_id]
        if key not in sample.channels:
            raise KeyError(key)
        if key not in self.project_channels:
            raise KeyError(f"No project channel {key!r} to inherit")
        sample.channel_overrides.pop(key, None)

    def skip_sample_channel(self, sample_id: str, key: str) -> None:
        sample = self.samples[sample_id]
        if key not in sample.channels:
            raise KeyError(key)
        sample.channel_overrides[key] = None

    def override_sample_channel(
        self, sample_id: str, key: str, *, name: str | None = None, settings=None
    ) -> ChannelOverride:
        """Select a local-only channel or override an inherited one."""
        sample = self.samples[sample_id]
        local = sample.channels[key]
        override = ChannelOverride(
            name=local.name if name is None else name,
            settings=local.settings if settings is None else settings,
        )
        sample.channel_overrides[key] = override
        return override

    def revert_sample_channel(self, sample_id: str, key: str) -> None:
        """Remove a local decision, inheriting when the project has the key."""
        self.samples[sample_id].channel_overrides.pop(key, None)

    def edit_channel(
        self,
        sample_id: str,
        key: str,
        *,
        name=None,
        settings=None,
        project_scope: bool | None = None,
    ) -> None:
        """Edit project scope for one sample, local scope for several."""
        sample = self.samples[sample_id]
        local = sample.channels[key]
        if project_scope is None:
            populated = sum(bool(item.channels) for item in self.samples.values())
            project_scope = populated <= 1
        if project_scope:
            project_channel = self.project_channels.get(key)
            if project_channel is None:
                project_channel = self.add_project_channel_from_sample(sample_id, key)
            if name is not None:
                project_channel.name = name
            if settings is not None:
                project_channel.settings = settings
            sample.channel_overrides.pop(key, None)
        else:
            current = sample.channel_overrides.get(key)
            if not isinstance(current, ChannelOverride):
                current = ChannelOverride(
                    name=(
                        self.project_channels[key].name
                        if key in self.project_channels
                        else local.name
                    ),
                    settings=local.settings,
                )
            if name is not None:
                current.name = name
            if settings is not None:
                current.settings = settings
            sample.channel_overrides[key] = current

    @staticmethod
    def _tiff_file_prefix(used_keys):
        index = 0
        while True:
            value = index
            letters = ""
            while True:
                value, remainder = divmod(value, 26)
                letters = chr(ord("A") + remainder) + letters
                if value == 0:
                    break
                value -= 1
            if not any(key == letters or key.startswith(f"{letters}-") for key in used_keys):
                return letters
            index += 1

    def _source_channels(self, source, channel_names=None, used_keys=()):
        candidates = source.list_elements()
        names = channel_names or {}
        proposal = infer_tiff_import(source.filename) if source.kind == "tiff" else None
        tiff_prefix = (
            self._tiff_file_prefix(used_keys)
            if proposal is not None and len(candidates) > 1
            else None
        )
        channels = []
        for index, candidate in enumerate(candidates):
            if candidate.ref.item_id in names:
                key, name = names[candidate.ref.item_id]
            elif candidate.key is not None:
                key = name = candidate.key
            elif proposal is not None:
                if tiff_prefix is None:
                    key = proposal.channel_key
                    name = proposal.channel_name
                else:
                    component_name = (
                        candidate.name
                        if candidate.name in {"Red", "Green", "Blue", "Alpha"}
                        else str(index + 1)
                    )
                    key = name = f"{tiff_prefix}-{component_name}"
            else:
                key = name = candidate.name
            channels.append(
                Channel(
                    key=key,
                    name=name,
                    ref=candidate.ref,
                    settings=self.element_settings.get(candidate.ref),
                    data_source=source.channel_data(candidate.ref),
                )
            )
        return channels

    def register_source(
        self, source: LoadedSource, *, sample_id=None, channel_names=None
    ) -> Sample:
        """Register a source, optionally adding it to an existing sample."""
        source_id = source.source_id
        existing_asset = self.assets.get(source_id)
        if existing_asset is not None:
            sample = self.samples[existing_asset.sample_id]
        elif sample_id is not None:
            sample = self.samples[sample_id]
        else:
            name = (
                infer_tiff_import(source.filename).sample_name
                if source.kind == "tiff"
                else source.alias
            )
            sample = Sample(str(uuid4()), name)

        channels = self._source_channels(source, channel_names, sample.channels)
        if source.kind == "tiff":
            for channel in channels:
                channel.data_source.array()
        sample.replace_asset_channels(source_id, channels)

        if sample.sample_id not in self.samples:
            self.samples[sample.sample_id] = sample
        if source_id not in sample.asset_ids:
            sample.asset_ids.append(source_id)
        self.assets[source_id] = DataAsset(
            asset_id=source_id,
            path=source.filename,
            source=source,
            sample_id=sample.sample_id,
            original_path=source.filename,
        )
        self.update_external_data_root()
        return sample

    def register_unavailable_source(
        self,
        source: LoadedSource,
        *,
        sample_id: str,
        channels,
        shape,
        original_path=None,
    ) -> Sample:
        """Restore a closed source and its channel identities from project metadata."""
        sample = self.samples[sample_id]
        restored = []
        for channel_obj in channels:
            ref = ElementRef(source.source_id, channel_obj["item_id"])
            restored.append(
                Channel(
                    key=channel_obj["key"],
                    name=channel_obj["name"],
                    ref=ref,
                    data_source=source.channel_data(ref),
                )
            )
        existing_keys = set(sample.channels)
        if existing_keys & {channel.key for channel in restored}:
            raise ValueError(f"Sample {sample.name!r} contains duplicate channel keys")
        sample.channels.update({channel.key: channel for channel in restored})
        sample.shape = tuple(shape) if shape is not None else sample.shape
        sample.asset_ids.append(source.source_id)
        self.assets[source.source_id] = DataAsset(
            asset_id=source.source_id,
            path=source.filename,
            source=source,
            sample_id=sample_id,
            original_path=original_path or source.filename,
        )
        return sample

    def update_external_data_root(self, project_dir=None) -> str | None:
        """Record the common parent of data outside the project directory."""
        project_path = Path(project_dir).resolve() if project_dir is not None else None
        external = []
        for asset in self.assets.values():
            path = Path(asset.path).resolve()
            if project_path is None or not path.is_relative_to(project_path):
                external.append(str(path.parent))
        if not external:
            self.external_data_root = None
        else:
            common = Path(os.path.commonpath(external))
            self.external_data_root = None if common == Path(common.anchor) else str(common)
        return self.external_data_root

    def replace_asset_path(self, asset_id: str, path: str) -> None:
        """Reopen an asset elsewhere without changing any stable references."""
        from .source_refs import open_source

        asset = self.assets[asset_id]
        replacement = open_source(path)
        try:
            if replacement.kind != asset.source.kind:
                raise ValueError(f"Replacement is {replacement.kind}, expected {asset.source.kind}")
            old_items = {
                channel.ref.item_id
                for channel in self.samples[asset.sample_id].channels.values()
                if channel.ref is not None and channel.ref.source_id == asset_id
            }
            new_items = {candidate.ref.item_id for candidate in replacement.list_elements()}
            if new_items != old_items:
                raise ValueError("Replacement does not contain the same maps")
            expected_shape = self.samples[asset.sample_id].shape
            for item_id in new_items:
                ref = ElementRef(replacement.source_id, item_id)
                if tuple(replacement.channel_data(ref).shape) != expected_shape:
                    raise ValueError("Replacement maps do not have the sample shape")

            source = asset.source
            alias = source.alias
            source.close()
            source.filename = replacement.filename
            source.alias = alias
            source.kind = replacement.kind
            source.handle = replacement.handle
            source.root = replacement.root
            replacement.handle = None
            replacement.root = None
            asset.path = source.filename
        finally:
            replacement.close()

    def replace_external_data_root(self, path: str) -> dict[str, str]:
        """Relocate files using their paths beneath the remembered external root."""
        if self.external_data_root is None:
            raise ValueError("The project has no common external data directory")
        old_root = Path(self.external_data_root)
        new_root = Path(path).resolve()
        failures = {}
        for asset in self.assets.values():
            try:
                relative = Path(asset.path).resolve().relative_to(old_root)
            except ValueError:
                continue
            candidate = new_root / relative
            try:
                self.replace_asset_path(asset.asset_id, str(candidate))
            except Exception as exc:
                failures[asset.asset_id] = str(exc)
        if not failures:
            self.external_data_root = str(new_root)
        return failures

    def rename_single_channel_tiff(self, asset_id: str, new_key: str) -> str:
        """Rename the channel supplied by a single-channel TIFF asset."""
        if not new_key:
            raise ValueError("Channel key must not be empty")
        asset = self.assets[asset_id]
        if asset.source.kind != "tiff":
            raise ValueError("Only TIFF channel keys can be edited")
        sample = self.samples[asset.sample_id]
        channels = [
            channel
            for channel in sample.channels.values()
            if channel.ref is not None and channel.ref.source_id == asset_id
        ]
        if len(channels) != 1:
            raise ValueError("Only single-channel TIFF keys can be edited")
        old_key = channels[0].key
        sample.rename_channel(old_key, new_key, name=new_key)
        if old_key in self.project_channels and not any(
            old_key in candidate.channels for candidate in self.samples.values()
        ):
            previous = self.project_channels.pop(old_key)
            if new_key not in self.project_channels:
                previous.key = new_key
                if previous.name == old_key:
                    previous.name = new_key
                self.project_channels[new_key] = previous
        return old_key

    def remove_asset(self, asset_id: str) -> list[Channel]:
        """Intentionally remove a file and its channels from the project."""
        asset = self.assets[asset_id]
        sample = self.samples[asset.sample_id]
        self.segmentation_results.pop(sample.sample_id, None)
        removed = sample.remove_asset_channels(asset_id)
        asset.source.close()
        self.assets.pop(asset_id)
        for channel in removed:
            if channel.ref is not None:
                self.element_settings.pop(channel.ref, None)
        available_keys = {key for candidate in self.samples.values() for key in candidate.channels}
        for key in list(self.project_channels):
            if key not in available_keys:
                self.project_channels.pop(key)
        self.update_external_data_root()
        return removed

    def remove_sample(self, sample_id: str) -> list[Channel]:
        """Intentionally remove a sample and all files assigned to it."""
        sample = self.samples[sample_id]
        removed = []
        for asset_id in list(sample.asset_ids):
            removed.extend(self.remove_asset(asset_id))
        self.segmentation_results.pop(sample_id, None)
        self.samples.pop(sample_id, None)
        return removed

    def set_element_settings(self, ref: ElementRef, settings: Any) -> None:
        """Store materialized settings and attach them to their channel."""
        self.element_settings[ref] = settings
        for sample in self.samples.values():
            for channel in sample.channels.values():
                if channel.ref == ref:
                    channel.settings = settings

    def channel_for_ref(self, ref: ElementRef):
        """Return ``(sample, channel)`` for a physical channel ref."""
        asset = self.assets.get(ref.source_id)
        if asset is None:
            raise KeyError(ref)
        sample = self.samples[asset.sample_id]
        for channel in sample.channels.values():
            if channel.ref == ref:
                return sample, channel
        raise KeyError(ref)

    def effective_refs(self) -> set[ElementRef]:
        refs = set()
        for sample in self.samples.values():
            refs.update(
                channel.ref for channel in sample.effective_channels(self.project_channels).values()
            )
        return refs

    def clear(self) -> None:
        """Clear all project-owned sample state without replacing containers."""
        self.assets.clear()
        self.samples.clear()
        self.project_channels.clear()
        self.images.clear()
        self.segmentation_results.clear()
        for settings in self.matrix_plot_settings.values():
            settings.reset()
        self.element_settings.clear()
        self.external_data_root = None
