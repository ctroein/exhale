"""Stable source/item identities and readers for Exhale element maps."""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import h5py
import numpy as np
import tifffile


@dataclass(frozen=True, order=True)
class ElementRef:
    """Identify a source by absolute filename and an element within it.

    HDF5 item IDs are dataset paths; TIFF item IDs are zero-based page/<n>.
    """

    source_id: str
    item_id: str

    @classmethod
    def from_json(cls, obj: dict[str, str]) -> "ElementRef":
        return cls(source_id=obj["source"], item_id=obj["item"])

    def to_json(self) -> dict[str, str]:
        return {"source": self.source_id, "item": self.item_id}

    @property
    def filename(self) -> str:
        return self.source_id


@dataclass
class ElementCandidate:
    """A selectable element, independent of its storage format."""

    ref: ElementRef
    name: str
    key: str | None = None


class SourceUnavailableError(RuntimeError):
    """Report attempted access to a source which could not be opened."""

    def __init__(self, source: "LoadedSource"):
        self.source_id = source.source_id
        message = f"The data file cannot be opened: {source.filename}"
        if source.open_error:
            message += f"\n\nCause: {source.open_error}"
        super().__init__(message)


@dataclass(frozen=True)
class TiffComponent:
    """One two-dimensional component extracted from a three-dimensional TIFF page."""

    page: Any
    axis: int
    index: int

    @property
    def shape(self):
        return tuple(size for axis, size in enumerate(self.page.shape) if axis != self.axis)

    @property
    def dtype(self):
        return self.page.dtype

    def asarray(self):
        return np.take(self.page.asarray(), self.index, axis=self.axis)


def _tiff_component_axis(page) -> int | None:
    """Return the non-spatial axis of a valid 3-D page, or None for a 2-D page."""
    if len(page.shape) == 2:
        return None
    if len(page.shape) != 3:
        raise ValueError(
            "TIFF maps must have two spatial dimensions and at most one component axis"
        )
    axes = page.axes
    if len(axes) != 3 or axes.count("Y") != 1 or axes.count("X") != 1:
        raise ValueError(f"Cannot identify two spatial axes in TIFF axes {axes!r}")
    return next(index for index, axis in enumerate(axes) if axis not in "YX")


def _ome_channel_names(handle) -> tuple[str | None, ...]:
    """Return channel names from a single OME image, if present."""
    if not handle.is_ome or not handle.ome_metadata or len(handle.series) != 1:
        return ()
    try:
        root = ET.fromstring(handle.ome_metadata)
    except ET.ParseError:
        return ()
    pixels = root.find(".//{*}Pixels")
    if pixels is None:
        return ()
    return tuple(
        name if (name := channel.get("Name", "").strip()) else None
        for channel in pixels.findall("{*}Channel")
    )


@dataclass
class LoadedSource:
    """Own the backing file; materialized element arrays survive close()."""

    source_id: str
    filename: str
    alias: str
    kind: str
    handle: Any | None = None
    root: h5py.Group | None = None
    tiff_channel_names: tuple[str | None, ...] = ()
    open_error: str | None = None

    @property
    def is_open(self) -> bool:
        return self.handle is not None

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
        self.handle = None
        self.root = None

    def display_name(self) -> str:
        suffix = "" if self.is_open else " [closed]"
        return f"{self.alias}{suffix}"

    def default_element_name(self, ref: ElementRef) -> str:
        if self.kind == "tiff":
            parts = ref.item_id.split("/")
            if len(parts) == 4 and parts[2] == "component":
                page = self.handle.pages[int(parts[1])]
                component = int(parts[3])
                if len(self.handle.pages) == 1 and component < len(self.tiff_channel_names):
                    if name := self.tiff_channel_names[component]:
                        return name
                if page.photometric == 2 and page.shape[_tiff_component_axis(page)] in (3, 4):
                    return ("Red", "Green", "Blue", "Alpha")[component]
                return f"{self.alias} [component {component + 1}]"
            page_index = int(parts[1])
            if len(self.tiff_channel_names) == len(self.handle.pages):
                if name := self.tiff_channel_names[page_index]:
                    return name
            if self.handle is not None and len(self.handle.pages) == 1:
                return self.alias
            return f"{self.alias} [page {page_index + 1}]"
        return ref.item_id.rsplit("/", 1)[-1]

    def list_elements(self) -> list[ElementCandidate]:
        if not self.is_open:
            return []
        if self.kind == "hdf5":
            return [
                ElementCandidate(ElementRef(self.source_id, entity.name), key, key)
                for key, entity in self.root.items()
                if isinstance(entity, h5py.Dataset)
            ]
        if self.kind == "tiff":
            refs = []
            for page_index, page in enumerate(self.handle.pages):
                component_axis = _tiff_component_axis(page)
                if component_axis is None:
                    refs.append(ElementRef(self.source_id, f"page/{page_index}"))
                else:
                    refs.extend(
                        ElementRef(self.source_id, f"page/{page_index}/component/{component_index}")
                        for component_index in range(page.shape[component_axis])
                    )
            candidates = []
            for ref in refs:
                name = self.default_element_name(ref)
                parts = ref.item_id.split("/")
                metadata_name = False
                if len(parts) == 2 and len(self.tiff_channel_names) == len(self.handle.pages):
                    metadata_name = self.tiff_channel_names[int(parts[1])] is not None
                elif len(parts) == 4 and len(self.handle.pages) == 1:
                    metadata_name = int(parts[3]) < len(self.tiff_channel_names) and (
                        self.tiff_channel_names[int(parts[3])] is not None
                    )
                candidates.append(ElementCandidate(ref, name, name if metadata_name else None))
            return candidates
        raise NotImplementedError(self.kind)

    def data_object(self, ref: ElementRef):
        """Return the HDF5 dataset or TIFF page identified by ``ref``."""
        if ref.source_id != self.source_id:
            raise ValueError(f"ElementRef belongs to {ref.source_id!r}, not {self.source_id!r}")
        if not self.is_open:
            raise SourceUnavailableError(self)
        if self.kind == "hdf5":
            item = self.handle[ref.item_id]
            if not isinstance(item, h5py.Dataset):
                raise ValueError(f"Not an HDF5 dataset: {ref.item_id}")
            return item
        elif self.kind == "tiff":
            parts = ref.item_id.split("/")
            if (
                len(parts) not in (2, 4)
                or parts[0] != "page"
                or not parts[1].isdecimal()
                or str(int(parts[1])) != parts[1]
                or int(parts[1]) >= len(self.handle.pages)
            ):
                raise ValueError(f"Invalid TIFF element: {ref.item_id!r}")
            page = self.handle.pages[int(parts[1])]
            if len(parts) == 2:
                if _tiff_component_axis(page) is not None:
                    raise ValueError(f"TIFF element requires a component: {ref.item_id!r}")
                return page
            if parts[2] != "component" or not parts[3].isdecimal():
                raise ValueError(f"Invalid TIFF element: {ref.item_id!r}")
            component = int(parts[3])
            if str(component) != parts[3]:
                raise ValueError(f"Invalid TIFF element: {ref.item_id!r}")
            axis = _tiff_component_axis(page)
            if axis is None or component >= page.shape[axis]:
                raise ValueError(f"Invalid TIFF element: {ref.item_id!r}")
            return TiffComponent(page, axis, component)
        else:
            raise NotImplementedError(self.kind)

    def channel_data(self, ref: ElementRef):
        """Return a cached-on-demand accessor for one channel map."""
        from .channeldata import SourceChannelData

        return SourceChannelData(self, ref)

    def load_array(self, ref: ElementRef) -> np.ndarray:
        item = self.data_object(ref)
        data = item[()] if self.kind == "hdf5" else item.asarray()
        if data.ndim != 2 or data.size == 0 or data.dtype.kind not in "buif":
            raise ValueError(f"Element {ref.item_id!r} must be a nonempty 2-D real-valued map")
        return data


def open_source(filename: str) -> LoadedSource:
    """Open and validate an HDF5 or TIFF map source.

    The returned object owns the file handle. A handle opened during a failed
    validation is closed before the exception is propagated.
    """

    filename = os.path.abspath(os.fspath(filename))
    alias = os.path.splitext(os.path.basename(filename))[0]
    if h5py.is_hdf5(filename):
        handle = h5py.File(filename, "r")
        try:
            default = handle.attrs.get("default")
            if isinstance(default, bytes):
                default = default.decode()
            group = handle[default] if isinstance(default, str) else None
            root = group.get("plotselect") if isinstance(group, h5py.Group) else None
            if not isinstance(root, h5py.Group):
                raise ValueError(f"{filename!r} needs /<default>/plotselect to load element maps")
            return LoadedSource(filename, filename, alias, "hdf5", handle, root)
        except Exception:
            handle.close()
            raise

    handle = tifffile.TiffFile(filename)
    try:
        if not len(handle.pages):
            raise ValueError(f"{filename!r} contains no TIFF pages")
        for index, page in enumerate(handle.pages):
            try:
                component_axis = _tiff_component_axis(page)
            except ValueError as exc:
                raise ValueError(f"TIFF page {index + 1}: {exc}") from exc
            map_shape = tuple(
                size for axis, size in enumerate(page.shape) if axis != component_axis
            )
            if len(map_shape) != 2 or not all(map_shape) or page.dtype.kind not in "buif":
                raise ValueError(f"TIFF page {index + 1} must contain nonempty 2-D numeric maps")
        return LoadedSource(
            filename,
            filename,
            alias,
            "tiff",
            handle,
            tiff_channel_names=_ome_channel_names(handle),
        )
    except Exception:
        handle.close()
        raise


def ref_display_basename(ref: ElementRef) -> str:
    """Return the final item-path component for compact display."""

    return ref.item_id.rsplit("/", 1)[-1] or ref.item_id
