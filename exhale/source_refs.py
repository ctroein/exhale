"""Stable source/item identities and readers for Exhale element maps."""

from dataclasses import dataclass
import os
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


@dataclass
class LoadedSource:
    """Own the backing file; materialized element arrays survive close()."""
    source_id: str
    filename: str
    alias: str
    kind: str
    handle: Any | None = None
    root: h5py.Group | None = None

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
            if self.handle is not None and len(self.handle.pages) == 1:
                return self.alias
            return f"{self.alias} [page {int(ref.item_id.split('/')[1]) + 1}]"
        return ref.item_id.rsplit("/", 1)[-1]

    def list_elements(self) -> list[ElementCandidate]:
        if not self.is_open:
            return []
        if self.kind == "hdf5":
            return [ElementCandidate(ElementRef(self.source_id, entity.name), key)
                    for key, entity in self.root.items()
                    if isinstance(entity, h5py.Dataset)]
        if self.kind == "tiff":
            refs = [ElementRef(self.source_id, f"page/{i}")
                    for i in range(len(self.handle.pages))]
            return [ElementCandidate(ref, self.default_element_name(ref))
                    for ref in refs]
        raise NotImplementedError(self.kind)

    def load_array(self, ref: ElementRef) -> np.ndarray:
        if ref.source_id != self.source_id:
            raise ValueError(f"ElementRef belongs to {ref.source_id!r}, "
                             f"not {self.source_id!r}")
        if not self.is_open:
            raise RuntimeError(f"Source is closed: {self.filename}")
        if self.kind == "hdf5":
            dataset = self.handle[ref.item_id]
            if not isinstance(dataset, h5py.Dataset):
                raise ValueError(f"Not an HDF5 dataset: {ref.item_id}")
            data = dataset[()]
        elif self.kind == "tiff":
            prefix, separator, number = ref.item_id.partition("/")
            if (prefix != "page" or not separator or not number.isdecimal() or
                    str(int(number)) != number or int(number) >= len(self.handle.pages)):
                raise ValueError(f"Invalid TIFF element: {ref.item_id!r}")
            data = self.handle.pages[int(number)].asarray()
        else:
            raise NotImplementedError(self.kind)
        if data.ndim != 2 or data.size == 0 or data.dtype.kind not in "buif":
            raise ValueError(f"Element {ref.item_id!r} must be a nonempty 2-D real-valued map")
        return data


def open_source(filename: str) -> LoadedSource:
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
            if (len(page.shape) != 2 or page.samplesperpixel != 1 or
                    page.photometric not in (0, 1) or
                    not all(page.shape) or page.dtype.kind not in "buif"):
                raise ValueError(f"TIFF page {index + 1} must be a nonempty 2-D grayscale map")
        return LoadedSource(filename, filename, alias, "tiff", handle)
    except Exception:
        handle.close()
        raise


def ref_display_basename(ref: ElementRef) -> str:
    return ref.item_id.rsplit("/", 1)[-1] or ref.item_id
