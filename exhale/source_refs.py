#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source_refs.py
--------------
Source and element-reference abstraction for EXHALE.

This module defines stable source/item identities for data that can be
selected as EXHALE elements.  UI and project code should use ElementRef
rather than raw (filename, dataset_path) tuples.
"""

from dataclasses import dataclass
from typing import Any
import os.path

import numpy as np
import silx.io

H5_ELEMENT_GROUP_NAMES = ("plotselect",)


@dataclass(frozen=True, order=True)
class ElementRef:
    """Stable identity for one selectable data item inside a loaded source.

    source_id:
        Stable source identifier.  During the transition this is normally the
        absolute filename, matching the old tuple-key first element.

    item_id:
        Stable item identifier inside the source.  For HDF5 this is the HDF5
        dataset path.  For a plain TIFF this can be "image" or "page/<n>".
    """

    source_id: str
    item_id: str

    @classmethod
    def from_h5_dataset(cls, dataset: Any) -> "ElementRef":
        return cls(source_id=dataset.file.filename, item_id=dataset.name)

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
    """One data item that can be shown/selected as an element."""
    ref: ElementRef
    name: str
    entity: Any = None


@dataclass
class LoadedSource:
    """A loaded file/source and its currently open backing handle.

    `handle` is deliberately allowed to become None.  Closing a file should
    close the external handle without necessarily deleting already materialized
    ElementSettings objects that are still used by images or analysis.
    """
    source_id: str
    filename: str
    alias: str
    kind: str
    handle: Any | None = None
    root: Any | None = None

    @classmethod
    def from_h5_group(cls, group: Any, alias: str | None = None) -> "LoadedSource":
        filename = group.file.filename
        return cls(
            source_id=filename,
            filename=filename,
            alias=alias if alias is not None else _default_alias(filename),
            kind="hdf5",
            handle=group.file,
            root=group,
        )

    @classmethod
    def from_tiff_dataset(cls, filename: str, dataset: Any,
                          alias: str | None = None) -> "LoadedSource":
        return cls(
            source_id=filename,
            filename=filename,
            alias=alias if alias is not None else _default_alias(filename),
            kind="tiff",
            handle=dataset.file,
            root=dataset,
        )

    @property
    def is_open(self) -> bool:
        return self.handle is not None

    def close(self) -> None:
        if self.handle is not None:
            close = getattr(self.handle, "close", None)
            if close is not None:
                close()
        self.handle = None
        self.root = None

    def display_name(self) -> str:
        suffix = "" if self.is_open else " [closed]"
        return f"{self.alias}{suffix}"

    def default_element_name(self, ref: ElementRef) -> str:
        if self.kind == "tiff":
            return self.alias
        return ref.item_id.rsplit("/", 1).pop()

    def list_elements(self) -> list[ElementCandidate]:
        """Return selectable element-like datasets for this source.

        HDF5 lists datasets immediately below `root`.
        TIFF returns one synthetic image item.
        """
        if self.kind == "hdf5":
            if self.root is None:
                return []
            out = []
            for key, entity in self.root.items():
                if silx.io.utils.is_dataset(entity):
                    ref = ElementRef(self.source_id, entity.name)
                    out.append(ElementCandidate(ref=ref, name=key, entity=entity))
            return out

        if self.kind == "tiff":
            if self.root is None:
                return []
            ref = ElementRef(self.source_id, self.root.name)
            return [ElementCandidate(ref=ref, name=self.alias, entity=self.root)]

        return []

    def load_array(self, ref: ElementRef) -> np.ndarray:
        """Load an ndarray for `ref` from this source."""
        if ref.source_id != self.source_id:
            raise ValueError(f"ElementRef belongs to {ref.source_id!r}, "
                             f"not {self.source_id!r}")

        if self.handle is None:
            raise RuntimeError(f"Source is closed: {self.filename}")
        if self.kind == "hdf5" or self.kind == "tiff":
            return self.handle[ref.item_id][()]

        raise NotImplementedError(self.kind)

def open_source(filename: str) -> LoadedSource:
    h5 = silx.io.open(filename)

    try:
        # PyMCA/EXHALE HDF5:
        # /<default>/plotselect/<datasets>
        default = h5.attrs.get("default", None)
        if isinstance(default, bytes):
            default = default.decode()

        if default is not None:
            group = h5[default]

            if "plotselect" in group:
                plotselect = group["plotselect"]
                if silx.io.utils.is_group(plotselect):
                    return LoadedSource.from_h5_group(plotselect)

            # TIFF via silx:
            # /scan_0/image
            if default == "scan_0" and "image" in group:
                image_group = group["image"]
                if ("data" in image_group and
                    silx.io.utils.is_dataset(image_group["data"])):
                    return LoadedSource.from_tiff_dataset(
                        filename, image_group["data"])

        raise ValueError(
            f"{filename!r} does not look like a supported PyMCA/EXHALE HDF5 "
            "file or a silx-loaded TIFF"
        )

    except Exception:
        close = getattr(h5, "close", None)
        if close is not None:
            close()
        raise

def _default_alias(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename))[0]

def ref_display_basename(ref: ElementRef) -> str:
    return ref.item_id.rsplit("/", 1)[-1] or ref.item_id

