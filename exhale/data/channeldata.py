"""Uniform access to in-memory and file-backed channel maps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .source_refs import ElementRef, LoadedSource


class ChannelData(ABC):
    """A two-dimensional numeric map with an optional disposable cache."""

    def __init__(self):
        self._cache: np.ndarray | None = None

    @property
    @abstractmethod
    def backing(self):
        """Return the underlying array, HDF5 dataset, or TIFF page."""

    @abstractmethod
    def _read(self) -> np.ndarray:
        """Read the complete map from its backing store."""

    @property
    def has_cache(self) -> bool:
        return self._cache is not None

    @property
    def is_available(self) -> bool:
        if self._cache is not None:
            return True
        try:
            return self.backing is not None
        except (OSError, RuntimeError, KeyError):
            return False

    @property
    def shape(self) -> tuple[int, int]:
        value = self._cache if self._cache is not None else self.backing
        return tuple(value.shape)

    @property
    def dtype(self) -> np.dtype:
        value = self._cache if self._cache is not None else self.backing
        return np.dtype(value.dtype)

    def array(self) -> np.ndarray:
        """Return a cached NumPy representation, reading it if necessary."""
        if self._cache is None:
            self._cache = np.asarray(self._read())
        return self._cache

    def release_cache(self) -> None:
        """Discard the materialized array; the backing data is unaffected."""
        self._cache = None


class ArrayChannelData(ChannelData):
    """Channel data whose backing store is already a NumPy array."""

    def __init__(self, data):
        super().__init__()
        self._array = np.asarray(data)
        self._cache = self._array

    @property
    def backing(self) -> np.ndarray:
        return self._array

    def _read(self) -> np.ndarray:
        return self._array

    def release_cache(self) -> None:
        # The array is the backing store, so releasing it cannot save memory.
        self._cache = self._array


class SourceChannelData(ChannelData):
    """A map backed by an item in an open input source."""

    def __init__(self, source: LoadedSource, ref: ElementRef):
        super().__init__()
        if ref.source_id != source.source_id:
            raise ValueError(f"ElementRef belongs to {ref.source_id!r}, not {source.source_id!r}")
        self.source = source
        self.ref = ref

    @property
    def backing(self):
        return self.source.data_object(self.ref)

    def _read(self) -> np.ndarray:
        return self.source.load_array(self.ref)


def as_channel_data(data) -> ChannelData:
    """Return ``data`` as a ChannelData object without copying arrays."""
    if isinstance(data, ChannelData):
        return data
    return ArrayChannelData(data)
