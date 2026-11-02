"""Backend-independent segmentation parameters and validated instance labels."""

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from skimage.segmentation import expand_labels


@dataclass(frozen=True)
class SegmentationPostprocessing:
    """Reversible boundary resizing followed by whole-instance area filtering."""

    minimum_area: int = 0
    expansion: int = 0

    def __post_init__(self):
        if isinstance(self.minimum_area, bool) or not isinstance(self.minimum_area, int):
            raise ValueError("Minimum segment area must be an integer")
        if self.minimum_area < 0:
            raise ValueError("Minimum segment area cannot be negative")
        if isinstance(self.expansion, bool) or not isinstance(self.expansion, int):
            raise ValueError("Segment expansion must be an integer")


def resize_segments(labels, distance):
    """Expand into background without overlap, or erode each instance separately.

    Distances are Euclidean source-image pixels. Expansion assigns background
    to the nearest label (ties follow expand_labels' deterministic convention).
    Erosion treats other labels and the image exterior as background, preserving
    surviving IDs even when segments touch or IDs are sparse.
    """
    if distance > 0:
        return expand_labels(labels, distance=distance)
    result = np.array(labels, copy=True)
    if distance == 0 or not np.any(labels):
        return result
    # Compact IDs only for finding bounding boxes; never alter output identities.
    _ids, inverse = np.unique(labels, return_inverse=True)
    compact = inverse.reshape(labels.shape) + 1
    compact[labels == 0] = 0
    for identity, bounds in enumerate(ndimage.find_objects(compact), start=1):
        if bounds is None:
            continue
        mask = compact[bounds] == identity
        distances = ndimage.distance_transform_edt(np.pad(mask, 1))[1:-1, 1:-1]
        result[bounds][mask & (distances <= -distance)] = 0
    return result


def segment_areas(labels):
    """Return positive instance IDs and their areas, including sparse label IDs."""
    identities, counts = np.unique(labels, return_counts=True)
    foreground = identities != 0
    return identities[foreground], counts[foreground]


def filter_segments(labels, minimum_area):
    """Copy labels, removing undersized instances without changing surviving IDs."""
    identities, counts = segment_areas(labels)
    filtered = np.array(labels, copy=True)
    filtered[np.isin(filtered, identities[counts < minimum_area])] = 0
    filtered.setflags(write=False)
    return filtered


@dataclass(frozen=True)
class SegmentationParameters:
    """Input preprocessing and inference options for one segmentation run."""

    clip_percentile: float | None = None
    method_options: dict = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class SegmentationOutput:
    """Instance labels and the identity of the trained model that produced them.

    Zero denotes background; positive integers identify instances. Copy labels
    so a backend or a later run cannot modify an existing result through an alias.
    """

    labels: np.ndarray
    model_id: str
    model_version: str

    def __post_init__(self):
        labels = np.asarray(self.labels)
        if labels.ndim != 2 or not all(labels.shape):
            raise ValueError("Segmentation labels must be a nonempty two-dimensional image")
        if not np.issubdtype(labels.dtype, np.integer) or np.any(labels < 0):
            raise ValueError("Segmentation labels must be nonnegative integers")
        if labels.max() > np.iinfo(np.uint32).max:
            raise ValueError("Segmentation instance IDs exceed the supported uint32 range")
        if not self.model_id or not self.model_version:
            raise ValueError("Segmentation output requires a model identity and version")
        object.__setattr__(self, "labels", np.array(labels, dtype=np.uint32, copy=True))
