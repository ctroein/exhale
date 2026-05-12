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

from __future__ import annotations

from dataclasses import dataclass
# from pathlib import Path
from typing import Any #, Iterable
import os.path

import numpy as np
import silx.io


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

    @property
    def h5path(self) -> str:
        """Compatibility alias for existing HDF5-oriented code."""
        return self.item_id


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
    def from_tiff(cls, filename: str, handle: Any | None = None,
                  alias: str | None = None) -> "LoadedSource":
        return cls(
            source_id=filename,
            filename=filename,
            alias=alias if alias is not None else _default_alias(filename),
            kind="tiff",
            handle=handle,
            root=None,
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

    def list_elements(self) -> list[ElementCandidate]:
        """Return selectable element-like datasets for this source.

        HDF5 currently lists datasets immediately below `root`, matching the
        previous `loadedFileChanged()` behavior.  TIFF returns one synthetic
        image item.
        """
        if self.kind == "hdf5":
            if self.root is None:
                return []
            out: list[ElementCandidate] = []
            for key, entity in self.root.items():
                if silx.io.utils.is_dataset(entity):
                    ref = ElementRef(self.source_id, entity.name)
                    out.append(ElementCandidate(ref=ref, name=key, entity=entity))
            return out

        if self.kind == "tiff":
            return [ElementCandidate(
                ref=ElementRef(self.source_id, "image"),
                name=self.alias,
                entity=None,
            )]

        return []

    def load_array(self, ref: ElementRef) -> np.ndarray:
        """Load an ndarray for `ref` from this source."""
        if ref.source_id != self.source_id:
            raise ValueError(f"ElementRef belongs to {ref.source_id!r}, not {self.source_id!r}")

        if self.kind == "hdf5":
            if self.handle is None:
                raise RuntimeError(f"Source is closed: {self.filename}")
            return self.handle[ref.item_id][()]

        if self.kind == "tiff":
            if self.handle is not None:
                try:
                    return self.handle[ref.item_id][()]
                except Exception:
                    pass

            from skimage import io
            data = io.imread(self.filename)
            if ref.item_id in ("image", "/"):
                return data
            if ref.item_id.startswith("page/"):
                return data[int(ref.item_id.split("/", 1)[1])]
            return data

        raise NotImplementedError(self.kind)


def _default_alias(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename))[0]


def ref_display_basename(ref: ElementRef) -> str:
    return ref.item_id.rsplit("/", 1)[-1] or ref.item_id
