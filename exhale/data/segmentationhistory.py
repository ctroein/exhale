"""Sample-owned segmentation candidates, run provenance and bounded history."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np

from .segmentation import SegmentationOutput, SegmentationParameters
from .source_refs import ElementRef

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .projectdata import LayerPresentation, SegmentationResult


def _identity() -> str:
    return str(uuid4())


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def partition_digest(labels: np.ndarray) -> str:
    """Identify region geometry independent of positive label IDs.

    Background remains zero. Positive IDs are canonicalized by their first
    occurrence, preserving the grouping of disconnected regions with one ID.
    Image shape is included, so equal flattened arrays of different shapes differ.
    """
    labels = np.asarray(labels)
    if labels.ndim != 2 or not np.issubdtype(labels.dtype, np.integer) or np.any(labels < 0):
        raise ValueError("A segmentation partition requires two-dimensional nonnegative integers")
    identities, first, inverse = np.unique(labels, return_index=True, return_inverse=True)
    order = np.argsort(first)
    foreground = order[identities[order] != 0]
    canonical = np.zeros(len(identities), dtype="<u4")
    canonical[foreground] = np.arange(1, len(foreground) + 1, dtype="<u4")
    digest = hashlib.sha256(np.asarray(labels.shape, dtype="<u8").tobytes())
    digest.update(canonical[inverse].tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class SegmentationRun:
    """An inference event, retained even if its mask duplicates another run."""

    method_id: str
    input_ref: ElementRef
    parameters: SegmentationParameters
    model_id: str
    model_version: str
    run_id: str = field(default_factory=_identity)
    created_at: str = field(default_factory=_timestamp)

    @classmethod
    def from_result(cls, result: SegmentationResult) -> SegmentationRun:
        """Snapshot parameters independently of subsequent option edits."""
        return cls(
            result.method_id,
            result.input_ref,
            deepcopy(result.parameters),
            result.output.model_id,
            result.output.model_version,
        )


@dataclass(eq=False)
class SegmentationCandidate:
    """One saved mask and its presentation, annotations and review identity.

    ``result`` holds an owned snapshot of the existing result model during the
    transition to candidate-based persistence. Run provenance can span methods;
    result.method_id describes its initial source, not a history lookup key.
    Label edits will create a child candidate, never mutate this snapshot.
    """

    result: SegmentationResult
    provenance: tuple[SegmentationRun, ...]
    candidate_id: str = field(default_factory=_identity)
    revision_id: str = field(default_factory=_identity)
    name: str = ""
    name_is_custom: bool = False
    created_at: str = field(default_factory=_timestamp)
    parent_id: str | None = None
    keep: bool = False
    edited: bool = False
    reviewed_revision: str | None = None
    compare: bool = False
    comparison_presentation: LayerPresentation | None = None
    labels_digest: str = field(init=False, repr=False)

    def __post_init__(self):
        if not self.candidate_id or not self.revision_id or self.parent_id == self.candidate_id:
            raise ValueError("Segmentation candidate requires distinct, nonempty identities")
        result = self.result
        output = SegmentationOutput(
            result.output.labels, result.output.model_id, result.output.model_version
        )
        output.labels.setflags(write=False)
        digest = hashlib.sha256(np.asarray(output.labels.shape, dtype="<u8").tobytes())
        digest.update(np.asarray(output.labels, dtype="<u4").tobytes())
        self.labels_digest = digest.hexdigest()
        self.result = replace(
            result,
            output=output,
            parameters=deepcopy(result.parameters),
            layer_settings=deepcopy(result.layer_settings),
            reference_refs=tuple(result.reference_refs),
        )
        self.provenance = deepcopy(tuple(self.provenance))

    @classmethod
    def from_result(cls, result: SegmentationResult) -> SegmentationCandidate:
        """Copy label data and mutable settings; discard disposable result caches."""
        return cls(result, (SegmentationRun.from_result(result),), name=result.method_id)

    @property
    def sample_id(self) -> str:
        return self.result.sample_id

    @property
    def reviewed(self) -> bool:
        return self.reviewed_revision == self.revision_id

    def set_reviewed(self, reviewed: bool) -> None:
        """Review applies to label identity, not to display or post-processing changes."""
        self.reviewed_revision = self.revision_id if reviewed else None

    @property
    def protected(self) -> bool:
        return self.keep or self.edited or self.reviewed or self.compare


class SegmentationHistory:
    """Own candidates for one sample, independently of segmentation method.

    Keep five recent unprotected predictions in addition to protected masks.
    The active mask and ancestors of retained edits cannot be automatically
    removed. Selection does not reorder history. Adding a run updates recency.
    This model performs no file writes or deletions.
    """

    def __init__(self, sample_id: str, recent_limit: int = 5):
        if not sample_id:
            raise ValueError("Segmentation history requires a sample identity")
        if isinstance(recent_limit, bool) or not isinstance(recent_limit, int) or recent_limit < 1:
            raise ValueError("Recent history limit must be a positive integer")
        self.sample_id = sample_id
        self.recent_limit = recent_limit
        self.candidates: dict[str, SegmentationCandidate] = {}
        self.active_id: str | None = None
        self._recency: list[str] = []
        self._digests: dict[str, str] = {}

    @property
    def active(self) -> SegmentationCandidate | None:
        return self.candidates.get(self.active_id)

    def activate(self, candidate_id: str) -> SegmentationCandidate:
        """Select a mask without changing its ordering or provenance."""
        candidate = self.candidates[candidate_id]
        self.active_id = candidate_id
        return candidate

    def latest_for_method(self, method_id: str) -> SegmentationCandidate | None:
        """Temporary method-selector adapter while the Mask chooser is introduced."""
        runs = [
            (run.created_at, run.run_id, candidate)
            for candidate in self.candidates.values()
            for run in candidate.provenance
            if run.method_id == method_id
        ]
        return max(runs, key=lambda item: item[:2])[2] if runs else None

    @property
    def recency(self) -> tuple[str, ...]:
        return tuple(self._recency)

    def equivalent(self, candidate: SegmentationCandidate) -> SegmentationCandidate | None:
        key = self._digests.get(partition_digest(candidate.result.output.labels))
        return self.candidates.get(key)

    @classmethod
    def restore(cls, sample_id, candidates, *, active_id=None, recency=(), recent_limit=5):
        """Restore complete snapshots before pruning, tolerating missing independent records."""
        history = cls(sample_id, recent_limit)
        issues = []
        aliases = {}
        for candidate in candidates:
            if candidate.sample_id != sample_id or candidate.candidate_id in history.candidates:
                issues.append("One segmentation candidate has a conflicting identity")
                continue
            existing = history.equivalent(candidate)
            if existing is not None:
                aliases[candidate.candidate_id] = existing.candidate_id
                runs = {run.run_id: run for run in existing.provenance}
                runs.update(
                    {run.run_id: run for run in candidate.provenance if run.run_id not in runs}
                )
                existing.provenance = tuple(runs.values())
                existing.keep |= candidate.keep
                existing.edited |= candidate.edited
                existing.compare |= candidate.compare
                if candidate.reviewed:
                    existing.set_reviewed(True)
                issues.append("Duplicate segmentation candidates were combined")
                continue
            history.candidates[candidate.candidate_id] = candidate
            history._digests[partition_digest(candidate.result.output.labels)] = (
                candidate.candidate_id
            )
        for candidate in history.candidates.values():
            parent = aliases.get(candidate.parent_id, candidate.parent_id)
            seen = {candidate.candidate_id}
            while parent is not None:
                if parent not in history.candidates or parent in seen:
                    candidate.parent_id = None
                    issues.append(
                        "One segmentation candidate's missing or cyclic parent was ignored"
                    )
                    break
                seen.add(parent)
                parent = aliases.get(
                    history.candidates[parent].parent_id, history.candidates[parent].parent_id
                )
            else:
                candidate.parent_id = aliases.get(candidate.parent_id, candidate.parent_id)
        for key in (*recency, *history.candidates):
            key = aliases.get(key, key)
            if key in history.candidates and key not in history._recency:
                history._recency.append(key)
        active_id = aliases.get(active_id, active_id)
        if active_id in history.candidates:
            history.active_id = active_id
        elif history._recency:
            history.active_id = history._recency[-1]
            if active_id is not None:
                issues.append("The unavailable active segmentation was replaced by a retained mask")
        history.prune()
        return history, issues

    def add_result(self, result: SegmentationResult) -> SegmentationCandidate:
        """Publish an owned prediction snapshot, merging identical region geometry."""
        if result.sample_id != self.sample_id:
            raise ValueError("Segmentation result belongs to a different sample")
        return self.add_candidate(SegmentationCandidate.from_result(result))

    def add_candidate(
        self, candidate: SegmentationCandidate, *, active_id=None
    ) -> SegmentationCandidate:
        """Retain or merge a mask, activate it, then prune unprotected predictions."""
        if candidate.sample_id != self.sample_id:
            raise ValueError("Segmentation candidate belongs to a different sample")
        if active_id is not None and active_id not in self.candidates:
            raise KeyError(active_id)
        if candidate.parent_id is not None and candidate.parent_id not in self.candidates:
            raise ValueError("The parent segmentation candidate is missing")
        digest = partition_digest(candidate.result.output.labels)
        existing_id = self._digests.get(digest)
        if candidate.candidate_id in self.candidates and existing_id != candidate.candidate_id:
            raise ValueError("Segmentation candidate identity already exists with different labels")
        if existing_id is not None:
            existing = self.candidates[existing_id]
            runs = {run.run_id: run for run in existing.provenance}
            for run in candidate.provenance:
                runs.setdefault(run.run_id, run)
            existing.provenance = tuple(runs.values())
            existing.keep |= candidate.keep
            existing.edited |= candidate.edited
            existing.compare |= candidate.compare
            if candidate.reviewed:
                existing.set_reviewed(True)
            candidate = existing
        else:
            self.candidates[candidate.candidate_id] = candidate
            self._digests[digest] = candidate.candidate_id
        self.active_id = candidate.candidate_id if active_id is None else active_id
        if candidate.candidate_id in self._recency:
            self._recency.remove(candidate.candidate_id)
        self._recency.append(candidate.candidate_id)
        self.prune()
        return candidate

    def remove(self, candidate_id: str) -> SegmentationCandidate:
        """Deliberately remove one mask, retaining descendants and immutable files.

        Direct children lose their parent link, not their labels or run provenance.
        Other candidates retain their order; the newest retained mask is the fallback.
        """
        removed = self.candidates.pop(candidate_id)
        self._recency.remove(candidate_id)
        self._digests = {
            digest: key for digest, key in self._digests.items() if key != candidate_id
        }
        comparison = f"comparison:{candidate_id}"
        for candidate in self.candidates.values():
            if candidate.parent_id == candidate_id:
                candidate.parent_id = None
            settings = candidate.result.layer_settings
            settings.order = tuple(key for key in settings.order if key != comparison)
            settings.layers.pop(comparison, None)
        if self.active_id == candidate_id:
            self.active_id = self._recency[-1] if self._recency else None
        return removed

    def prune(self) -> tuple[SegmentationCandidate, ...]:
        """Remove old predictions from memory, preserving masks needed by retained edits."""
        protected = {key for key, candidate in self.candidates.items() if candidate.protected}
        if self.active_id is not None:
            protected.add(self.active_id)
        recent = [key for key in self._recency if not self.candidates[key].protected]
        keep = protected | set(recent[-self.recent_limit :])
        for key in tuple(keep):
            parent = self.candidates[key].parent_id
            while parent is not None and parent not in keep:
                keep.add(parent)
                parent = self.candidates[parent].parent_id
        removed = tuple(candidate for key, candidate in self.candidates.items() if key not in keep)
        for candidate in removed:
            self.candidates.pop(candidate.candidate_id)
            self._recency.remove(candidate.candidate_id)
        removed_ids = {candidate.candidate_id for candidate in removed}
        self._digests = {
            digest: key for digest, key in self._digests.items() if key not in removed_ids
        }
        return removed

    @classmethod
    def from_results(
        cls, sample_id: str, results: Iterable[SegmentationResult], *, recent_limit: int = 5
    ) -> tuple[SegmentationHistory, list[str]]:
        """Convert usable existing results independently; report malformed entries.

        Existing method-based results have no run timestamp. Imported records
        receive an import timestamp without guessing their historical order.
        """
        history = cls(sample_id, recent_limit)
        issues = []
        for result in results:
            try:
                history.add_result(result)
            except (AttributeError, TypeError, ValueError) as exc:
                issues.append(f"One segmentation candidate was skipped: {exc}")
        return history, issues
