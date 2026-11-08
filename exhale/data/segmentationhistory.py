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
        self._removed = []

    @property
    def active(self) -> SegmentationCandidate | None:
        return self.candidates.get(self.active_id)

    @property
    def reviewed(self) -> SegmentationCandidate | None:
        """Return this sample's reviewed revision independently of the active mask."""
        reviewed = [candidate for candidate in self.candidates.values() if candidate.reviewed]
        if len(reviewed) > 1:
            raise ValueError("A sample has more than one reviewed segmentation")
        return reviewed[0] if reviewed else None

    def set_reviewed(self, candidate_id: str, reviewed: bool = True) -> None:
        """Transfer whole-image review without reordering or changing label data."""
        candidate = self.candidates[candidate_id]
        if reviewed:
            for other in self.candidates.values():
                if other is not candidate:
                    other.set_reviewed(False)
        candidate.set_reviewed(reviewed)

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
        digest = partition_digest(candidate.result.output.labels)
        key = self._digests.get(digest)
        if key is None:
            # Edited masks may intentionally coincide with a retained prediction.
            key = next(
                (
                    key
                    for key, value in self.candidates.items()
                    if partition_digest(value.result.output.labels) == digest
                ),
                None,
            )
            if key is not None:
                self._digests[digest] = key
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
            if existing is not None and not candidate.edited and not existing.edited:
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
        reviewed = [key for key in history._recency if history.candidates[key].reviewed]
        if len(reviewed) > 1:
            history.set_reviewed(reviewed[-1])
            issues.append("Multiple reviewed masks were reduced to the most recent retained mask")
        history.prune()
        return history, issues

    def add_result(self, result: SegmentationResult) -> SegmentationCandidate:
        """Publish an owned prediction snapshot, merging identical region geometry."""
        if result.sample_id != self.sample_id:
            raise ValueError("Segmentation result belongs to a different sample")
        return self.add_candidate(SegmentationCandidate.from_result(result))

    def add_candidate(
        self, candidate: SegmentationCandidate, *, active_id=None, deduplicate=True
    ) -> SegmentationCandidate:
        """Retain or merge a mask, activate it, then prune unprotected predictions."""
        if candidate.sample_id != self.sample_id:
            raise ValueError("Segmentation candidate belongs to a different sample")
        if active_id is not None and active_id not in self.candidates:
            raise KeyError(active_id)
        if candidate.parent_id is not None and candidate.parent_id not in self.candidates:
            raise ValueError("The parent segmentation candidate is missing")
        digest = partition_digest(candidate.result.output.labels)
        existing = self.candidates.get(candidate.candidate_id)
        if existing is not None:
            if partition_digest(existing.result.output.labels) != digest:
                raise ValueError(
                    "Segmentation candidate identity already exists with different labels"
                )
        elif deduplicate:
            existing = self.equivalent(candidate)
        existing_id = None if existing is None else existing.candidate_id
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
        if candidate.reviewed:
            self.set_reviewed(candidate.candidate_id)
        self.prune()
        return candidate

    def empty_mask(self, input_ref: ElementRef) -> SegmentationCandidate | None:
        """Find an existing blank mask for the selected source map."""
        return next(
            (
                candidate
                for candidate in self.candidates.values()
                if candidate.result.input_ref == input_ref
                and not candidate.result.output.labels.any()
            ),
            None,
        )

    def accept_edit(self, source_id, draft: SegmentationCandidate, *, active_id=None):
        """Fork a prediction once, then advance revisions of the same working mask.

        Replaced pixels are not archived. Downstream references retain their own
        old identity and become outdated when the current revision changes.
        """
        source = self.candidates[source_id]
        if draft.sample_id != self.sample_id or draft.parent_id != source_id:
            raise ValueError("The editing draft does not belong to this mask")
        if active_id is not None and active_id not in self.candidates:
            raise KeyError(active_id)
        if not source.edited:
            return self.add_candidate(draft, active_id=active_id)
        candidate = replace(
            draft,
            candidate_id=source.candidate_id,
            name=source.name,
            name_is_custom=source.name_is_custom,
            parent_id=source.parent_id,
            created_at=source.created_at,
            keep=source.keep,
            compare=source.compare,
            comparison_presentation=source.comparison_presentation,
        )
        self.candidates[source_id] = candidate
        self._digests = {digest: key for digest, key in self._digests.items() if key != source_id}
        self._digests.setdefault(partition_digest(candidate.result.output.labels), source_id)
        self.active_id = source_id if active_id is None else active_id
        return candidate

    def remove(self, candidate_id: str) -> SegmentationCandidate:
        """Deliberately remove one mask, retaining descendants and removal undo.

        Direct children lose their parent link, not their labels or run provenance.
        Other candidates retain their order; the newest retained mask is the fallback.
        """
        removed = self.candidates[candidate_id]
        position = list(self.candidates).index(candidate_id)
        children = [
            key for key, candidate in self.candidates.items() if candidate.parent_id == candidate_id
        ]
        comparison = f"comparison:{candidate_id}"
        comparisons = {}
        for key, candidate in self.candidates.items():
            settings = candidate.result.layer_settings
            if comparison in settings.layers:
                comparisons[key] = (
                    settings.order.index(comparison) if comparison in settings.order else None,
                    settings.layers[comparison],
                )
        self.candidates.pop(candidate_id)
        self._removed.append((removed, position, children, comparisons))
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

    @property
    def can_restore_removed(self) -> bool:
        """Whether this open sample has a deliberately removed mask to restore."""
        return bool(self._removed)

    def restore_removed(self) -> SegmentationCandidate | None:
        """Restore the latest removal without displacing a newer review assignment.

        Removal history is session-only and separate from label-edit undo.
        Descendant links and comparison presentation are restored where the
        affected masks still exist and have not acquired another parent.
        """
        if not self._removed:
            return None
        candidate, position, children, comparisons = self._removed[-1]
        if self.reviewed is not None:
            candidate.set_reviewed(False)
        if candidate.parent_id not in self.candidates:
            candidate.parent_id = None
        restored = self.add_candidate(candidate, deduplicate=False)
        self._removed.pop()
        items = [
            (key, value) for key, value in self.candidates.items() if key != restored.candidate_id
        ]
        items.insert(min(position, len(items)), (restored.candidate_id, restored))
        self.candidates.clear()
        self.candidates.update(items)
        for key in children:
            child = self.candidates.get(key)
            if child is not None and child.parent_id is None:
                child.parent_id = restored.candidate_id
        comparison = f"comparison:{restored.candidate_id}"
        for key, (index, presentation) in comparisons.items():
            other = self.candidates.get(key)
            if other is None:
                continue
            settings = other.result.layer_settings
            settings.layers.setdefault(comparison, presentation)
            if index is not None and comparison not in settings.order:
                order = list(settings.order)
                order.insert(min(index, len(order)), comparison)
                settings.order = tuple(order)
        return restored

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
