"""Immutable, serializable segmentation inputs for downstream computations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from .segmentation import SegmentationPostprocessing, filter_segments, resize_segments

if TYPE_CHECKING:
    import numpy as np

    from .segmentationhistory import SegmentationCandidate


@dataclass(frozen=True)
class SegmentationReference:
    """Record the exact accepted mask revision and processing used by a consumer.

    Consumers store this with their results and compare it with their intended
    input to determine whether those results are outdated. Viewer selection,
    names, colors, review status and run provenance do not identify label data.
    """

    sample_id: str
    candidate_id: str
    revision_id: str
    postprocessing: SegmentationPostprocessing

    def __post_init__(self):
        if any(
            not isinstance(value, str) or not value
            for value in (self.sample_id, self.candidate_id, self.revision_id)
        ):
            raise ValueError("A segmentation reference requires sample, candidate and revision IDs")
        if not isinstance(self.postprocessing, SegmentationPostprocessing):
            raise ValueError("A segmentation reference requires post-processing settings")

    @classmethod
    def from_candidate(cls, candidate: SegmentationCandidate) -> SegmentationReference:
        """Capture immutable settings, independently of later candidate changes."""
        return cls(
            candidate.sample_id,
            candidate.candidate_id,
            candidate.revision_id,
            candidate.result.postprocessing,
        )

    def identifies(self, candidate: SegmentationCandidate | None) -> bool:
        """Check label identity without considering current post-processing controls."""
        return candidate is not None and (self.sample_id, self.candidate_id, self.revision_id) == (
            candidate.sample_id,
            candidate.candidate_id,
            candidate.revision_id,
        )

    def matches(self, candidate: SegmentationCandidate | None) -> bool:
        """Whether results using this input remain current for the chosen candidate."""
        return self.identifies(candidate) and self.postprocessing == candidate.result.postprocessing

    def labels(self, candidate: SegmentationCandidate | None) -> np.ndarray:
        """Resolve recorded processing, never substitute another mask or current settings.

        Missing or changed label revisions raise ValueError. Changed processing
        controls do not prevent resolving the original input while its mask is
        retained. The returned labels are read-only; no project settings change.
        """
        if not self.identifies(candidate):
            raise ValueError("The referenced segmentation mask revision is unavailable")
        if self.matches(candidate):
            return candidate.result.processed_labels
        labels = candidate.result.output.labels
        if self.postprocessing.expansion:
            labels = resize_segments(labels, self.postprocessing.expansion)
        return filter_segments(labels, self.postprocessing.minimum_area)

    def to_json(self) -> dict:
        """Return a JSON-compatible record for inclusion in a consumer's saved result."""
        return asdict(self)

    @classmethod
    def from_json(cls, obj) -> SegmentationReference:
        """Read an exact reference; missing identity or processing cannot be inferred."""
        try:
            processing = obj["postprocessing"]
            return cls(
                obj["sample_id"],
                obj["candidate_id"],
                obj["revision_id"],
                SegmentationPostprocessing(
                    minimum_area=processing["minimum_area"],
                    expansion=processing["expansion"],
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid segmentation reference: {exc}") from exc
