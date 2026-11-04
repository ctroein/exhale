"""Undoable working-mask sessions backed by immutable candidate snapshots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from skimage.draw import line, polygon

from .segmentation import SegmentationOutput, segment_areas
from .segmentationhistory import SegmentationCandidate, partition_digest


@dataclass
class _Change:
    bounds: tuple[slice, slice]
    before: np.ndarray
    after: np.ndarray
    before_revision: str
    after_revision: str
    before_pending: frozenset[int]
    after_pending: frozenset[int]


class SegmentationEditSession:
    """Own a mutable working copy; retain only changed rectangular patches for undo.

    Entering a session changes neither the source candidate nor saved state.
    Changed sessions expose an immutable draft snapshot for normal save/autosave.
    Undo history and selected IDs are session-only viewer state.
    """

    def __init__(self, source: SegmentationCandidate):
        self.source = source
        self.candidate_id = str(uuid4())
        self.revision_id = str(uuid4())
        self.created_at = datetime.now(UTC).isoformat()
        self._labels = source.result.output.labels.copy()
        self.selected_ids: set[int] = set()
        self._undo: list[_Change] = []
        self._redo: list[_Change] = []
        self._snapshot = None
        self._areas = None
        self.changed = False
        self.pending_disconnections: set[int] = set()

    @property
    def labels(self):
        view = self._labels.view()
        view.setflags(write=False)
        return view

    @property
    def areas(self):
        if self._areas is None:
            self._areas = segment_areas(self._labels)
        return self._areas

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def select(self, identity: int, *, toggle=False):
        """Select a segment or toggle its membership; background clears selection."""
        if identity == 0:
            self.selected_ids.clear()
        elif identity in self.areas[0]:
            if not toggle:
                self.selected_ids = {identity}
            elif identity in self.selected_ids:
                self.selected_ids.remove(identity)
            else:
                self.selected_ids.add(identity)

    def apply_labels(self, labels, *, pending=None):
        """Commit one complete operation, rejecting invalid data before any mutation."""
        validated = SegmentationOutput(labels, "annotation", "working").labels
        if validated.shape != self._labels.shape:
            raise ValueError("Editing cannot change the mask dimensions")
        ys, xs = np.nonzero(validated != self._labels)
        if not len(ys):
            return False
        bounds = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        change = _Change(
            bounds,
            self._labels[bounds].copy(),
            validated[bounds].copy(),
            self.revision_id,
            str(uuid4()),
            frozenset(self.pending_disconnections),
            frozenset(self.pending_disconnections if pending is None else pending),
        )
        self._undo.append(change)
        self._redo.clear()
        self._apply(change.after, bounds, change.after_revision, change.after_pending)
        return True

    def _apply(self, data, bounds, revision, pending):
        self.pending_disconnections = set(pending)
        self._labels[bounds] = data
        self.revision_id = revision
        self._snapshot = None
        self._areas = None
        self.changed = not np.array_equal(self._labels, self.source.result.output.labels)
        self.selected_ids.intersection_update(map(int, self.areas[0]))

    def undo(self):
        """Revert one complete operation, restoring its previous revision identity."""
        if self._undo:
            change = self._undo.pop()
            self._apply(change.before, change.bounds, change.before_revision, change.before_pending)
            self._redo.append(change)

    def redo(self):
        """Reapply the last undone operation without generating another revision."""
        if self._redo:
            change = self._redo.pop()
            self._apply(change.after, change.bounds, change.after_revision, change.after_pending)
            self._undo.append(change)

    @staticmethod
    def _components(labels, identity):
        return ndimage.label(labels == identity, structure=np.ones((3, 3), dtype=bool))

    @staticmethod
    def _unused_id(labels, reserved=()):
        used = set(map(int, np.unique(labels))) | set(reserved)
        identity = 1
        while identity in used:
            identity += 1
        if identity > np.iinfo(np.uint32).max:
            raise ValueError("No unused segment identifiers remain")
        return identity

    @staticmethod
    def brush_mask(shape, points, size):
        """Rasterize a pixel-snapped round brush of integer diameter, without stroke gaps."""
        if not np.isfinite(size) or size < 1 or int(size) != size:
            raise ValueError("Brush size must be a positive integer number of pixels")
        points = np.asarray(points, dtype=float)
        radius = size / 2
        # Odd diameters are centered on pixels; even diameters on intersections.
        points = np.floor(points + 0.5) if size % 2 else np.floor(points) + 0.5
        mask = np.zeros(shape, dtype=bool)
        if not len(points):
            return mask
        # A capsule around each line segment avoids gaps even for fast drags.
        for start, end in zip(points, np.concatenate((points[1:], points[-1:])), strict=True):
            low = np.maximum(0, np.ceil(np.minimum(start, end) - radius).astype(int))
            high = np.minimum(shape, np.floor(np.maximum(start, end) + radius).astype(int) + 1)
            if np.any(high <= low):
                continue
            y, x = np.mgrid[low[0] : high[0], low[1] : high[1]]
            delta = end - start
            length = float(delta @ delta)
            t = (
                0
                if length == 0
                else np.clip(((y - start[0]) * delta[0] + (x - start[1]) * delta[1]) / length, 0, 1)
            )
            hit = (y - start[0] - t * delta[0]) ** 2 + (
                x - start[1] - t * delta[1]
            ) ** 2 <= radius**2
            mask[low[0] : high[0], low[1] : high[1]] |= hit
        return mask

    def preview(self, tool, points, *, size=5, protect=True):
        """Build a gesture's proposed labels without committing or changing the session."""
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("Editing points must be finite image coordinates")
        labels = self._labels.copy()
        if tool == "split":
            if len(self.selected_ids) != 1:
                raise ValueError("Select one segment to split")
            # The dividing line is a viewer-only preview; labels change on release.
            return labels
        outline = tool in ("draw", "outline_add", "outline_remove")
        operation = {"outline_add": "add", "outline_remove": "remove"}.get(tool, tool)
        if operation == "add" and len(self.selected_ids) != 1:
            raise ValueError("Select one segment before drawing into it")
        if operation == "remove" and protect and not self.selected_ids:
            raise ValueError("Select a segment before erasing from it")
        if outline:
            if len(points) < 3:
                return labels
            mask = np.zeros(labels.shape, dtype=bool)
            mask[polygon(points[:, 0], points[:, 1], labels.shape)] = True
        elif operation in ("add", "remove"):
            mask = self.brush_mask(labels.shape, points, size)
        else:
            raise ValueError(f"Unknown editing tool {tool!r}")
        if operation == "draw":
            if protect:
                mask &= labels == 0
            if mask.any():
                labels[mask] = self._unused_id(labels)
        elif operation == "add":
            identity = next(iter(self.selected_ids))
            if protect:
                mask &= (labels == 0) | (labels == identity)
            labels[mask] = identity
        elif operation == "remove":
            if protect:
                mask &= np.isin(labels, list(self.selected_ids))
            labels[mask] = 0
        return labels

    def _split_parts(self, labels, identity):
        """Retain the largest part's ID and allocate IDs for the remaining parts."""
        components, count = self._components(labels, identity)
        if count < 2:
            return
        sizes = np.bincount(components.ravel())
        largest = int(np.argmax(sizes[1:]) + 1)
        for part in range(1, count + 1):
            if part != largest:
                labels[components == part] = self._unused_id(labels)

    def _commit_edit(self, labels, disconnected):
        if disconnected not in ("keep", "split", "ask"):
            raise ValueError("Unknown disconnected-parts policy")
        changed = labels != self._labels
        affected = set(map(int, np.unique(self._labels[changed]))) | set(
            map(int, np.unique(labels[changed]))
        )
        affected.discard(0)
        pending = self.pending_disconnections.copy()
        for identity in sorted(affected | pending):
            _components, count = self._components(labels, identity)
            if count <= 1:
                pending.discard(identity)
            elif identity in affected:
                _before, previous_count = self._components(self._labels, identity)
                newly_disconnected = count > previous_count
                if disconnected == "split" and (newly_disconnected or identity in pending):
                    self._split_parts(labels, identity)
                    pending.discard(identity)
                elif disconnected == "ask" and newly_disconnected:
                    pending.add(identity)
                elif disconnected == "keep":
                    pending.discard(identity)
        return self.apply_labels(labels, pending=pending)

    def part_count(self, identity):
        """Return the number of eight-connected parts belonging to one instance."""
        return self._components(self._labels, identity)[1]

    def edit(self, tool, points, *, size=5, protect=True, disconnected="ask"):
        """Commit one complete outline/stroke, including incidental splitting, atomically."""
        if tool == "split":
            return self.split_selected(points)
        labels = self.preview(tool, points, size=size, protect=protect)
        previous_ids = set(map(int, self.areas[0]))
        changed = self._commit_edit(labels, disconnected)
        if changed and tool == "draw":
            self.selected_ids = set(map(int, self.areas[0])) - previous_ids
        return changed

    def merge_selected(self):
        """Merge the selection in one command, retaining its largest instance's ID."""
        if len(self.selected_ids) < 2:
            raise ValueError("Select at least two segments to merge")
        labels = self._labels.copy()
        ids, counts = self.areas
        selected = sorted(self.selected_ids)
        identity = max(
            selected, key=lambda value: (int(counts[np.searchsorted(ids, value)]), -value)
        )
        labels[np.isin(labels, selected)] = identity
        changed = self.apply_labels(labels, pending=self.pending_disconnections - self.selected_ids)
        if changed:
            self.selected_ids = {identity}
        return changed

    @staticmethod
    def _cut_components(mask, cut):
        """Find eight-connected parts while blocking diagonal links across the cut."""
        parts, count = ndimage.label(mask & ~cut)
        if not count:
            return parts, 0
        links = []
        # A one-pixel diagonal line must block the opposite diagonal connection,
        # while unrelated corner contacts in the original segment remain joined.
        for a, b, crossed in (
            (parts[:-1, :-1], parts[1:, 1:], cut[:-1, 1:] & cut[1:, :-1]),
            (parts[:-1, 1:], parts[1:, :-1], cut[:-1, :-1] & cut[1:, 1:]),
        ):
            connected = (a > 0) & (b > 0) & (a != b) & ~crossed
            links.extend(zip(a[connected] - 1, b[connected] - 1, strict=True))
        if links:
            rows, cols = np.asarray(links).T
            graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(count, count))
            count, groups = connected_components(graph, directed=False)
            foreground = parts > 0
            parts[foreground] = groups[parts[foreground] - 1] + 1
        return parts, count

    def split_selected(self, points):
        """Split along a stroke atomically, retaining all pixels and unrelated IDs.

        Failed cuts leave labels, pending questions, revisions and undo untouched.
        The largest resulting part retains the original ID; other parts get unused IDs.
        """
        if len(self.selected_ids) != 1:
            raise ValueError("Select one segment to split")
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("A dividing stroke requires finite image coordinates")
        if len(points) < 2 or not np.any(points[1:] != points[0]):
            raise ValueError("Draw a dividing stroke through the selected segment")
        identity = next(iter(self.selected_ids))
        selected = self._labels == identity
        ys, xs = np.nonzero(selected)
        low = np.array((ys.min(), xs.min()))
        high = np.array((ys.max() + 1, xs.max() + 1))
        bounds = (slice(low[0], high[0]), slice(low[1], high[1]))
        mask = selected[bounds]
        cut = np.zeros(mask.shape, dtype=bool)
        points = np.floor(points - low + 0.5).astype(int)
        for start, end in zip(points[:-1], points[1:], strict=True):
            y, x = line(*start, *end)
            valid = (y >= 0) & (y < mask.shape[0]) & (x >= 0) & (x < mask.shape[1])
            cut[y[valid], x[valid]] = True
        parts, count = self._cut_components(mask, cut)
        if count <= self._components(self._labels, identity)[1]:
            raise ValueError(
                "The stroke did not divide the segment. Draw through it from edge to edge."
            )
        # Assign the cut pixels to their nearest surviving part instead of erasing
        # a strip from the mask. The original foreground area is preserved exactly.
        nearest = ndimage.distance_transform_edt(
            parts == 0, return_distances=False, return_indices=True
        )
        parts[mask & cut] = parts[tuple(nearest[:, mask & cut])]
        sizes = np.bincount(parts[mask])
        largest = int(np.argmax(sizes[1:]) + 1)
        labels = self._labels.copy()
        region = labels[bounds]
        output_ids = {identity}
        for part in range(1, count + 1):
            value = identity if part == largest else self._unused_id(labels, output_ids)
            region[mask & (parts == part)] = value
            output_ids.add(value)
        changed = self.apply_labels(labels, pending=self.pending_disconnections - {identity})
        if changed:
            self.selected_ids = output_ids
        return changed

    def delete_selected(self):
        """Delete all selected instances in one undoable operation."""
        labels = self._labels.copy()
        labels[np.isin(labels, list(self.selected_ids))] = 0
        return self._commit_edit(labels, "keep")

    def resolve_disconnection(self, identity, *, split):
        """Record a keep decision, or commit the split as an undoable operation."""
        if identity not in self.pending_disconnections:
            return False
        pending = self.pending_disconnections - {identity}
        if split:
            labels = self._labels.copy()
            self._split_parts(labels, identity)
            return self.apply_labels(labels, pending=pending)
        self.pending_disconnections = pending
        return False

    def snapshot(self) -> SegmentationCandidate:
        """Return a stable draft identity; label files change only after an operation."""
        if self._snapshot is None:
            result = replace(
                self.source.result,
                output=SegmentationOutput(
                    self._labels,
                    self.source.result.output.model_id,
                    self.source.result.output.model_version,
                ),
            )
            self._snapshot = SegmentationCandidate(
                result,
                self.source.provenance,
                candidate_id=self.candidate_id,
                revision_id=self.revision_id,
                parent_id=self.source.candidate_id,
                edited=True,
                created_at=self.created_at,
            )
        # Presentation may change without a label operation; never copy arrays again.
        self._snapshot.result.layer_settings = deepcopy(self.source.result.layer_settings)
        self._snapshot.result.reference_refs = self.source.result.reference_refs
        self._snapshot.result.postprocessing = self.source.result.postprocessing
        return self._snapshot

    def completed_candidate(self) -> SegmentationCandidate | None:
        """Finish without creating history for unchanged or merely renumbered masks."""
        if not self.changed or partition_digest(self._labels) == partition_digest(
            self.source.result.output.labels
        ):
            return None
        return self.snapshot()

    @classmethod
    def restore(cls, source, draft, *, pending=()):
        """Resume saved labels against their retained source, with empty undo history."""
        if draft.parent_id != source.candidate_id or draft.sample_id != source.sample_id:
            raise ValueError("The working mask does not belong to its source candidate")
        if draft.result.output.labels.shape != source.result.output.labels.shape:
            raise ValueError("The working mask dimensions differ from its source")
        session = cls(source)
        session.candidate_id = draft.candidate_id
        session.revision_id = draft.revision_id
        session.created_at = draft.created_at
        session._labels = draft.result.output.labels.copy()
        session.changed = not np.array_equal(session._labels, source.result.output.labels)
        session._snapshot = draft
        identities = set(map(int, session.areas[0]))
        session.pending_disconnections = {
            int(identity) for identity in pending if int(identity) in identities
        }
        return session
