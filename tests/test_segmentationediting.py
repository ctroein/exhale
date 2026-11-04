"""Working-mask ownership, undo/redo, selection and completed revision contracts."""

import numpy as np
import pytest

from exhale.data.projectdata import SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.segmentationediting import SegmentationEditSession
from exhale.data.segmentationhistory import SegmentationCandidate, SegmentationHistory
from exhale.data.source_refs import ElementRef


def source():
    candidate = SegmentationCandidate.from_result(
        SegmentationResult(
            "sample",
            "stardist",
            ElementRef("data.h5", "/P"),
            SegmentationParameters(),
            SegmentationOutput(np.array([[0, 42, 42], [7, 0, 7]], dtype=np.uint32), "model", "1"),
        )
    )
    candidate.set_reviewed(True)
    return candidate


def test_selection_does_not_change_source_or_create_revision():
    original = source()
    session = SegmentationEditSession(original)
    session.select(42)
    session.select(7, toggle=True)
    assert session.selected_ids == {42, 7}
    session.select(42, toggle=True)
    assert session.selected_ids == {7}
    session.select(0)
    assert not session.selected_ids
    assert not session.changed and not session.can_undo and session.completed_candidate() is None
    assert original.reviewed
    assert not session.labels.flags.writeable


def test_complete_operations_undo_redo_and_snapshot_identity():
    original = source()
    session = SegmentationEditSession(original)
    edited = session.labels.copy()
    edited[0, 0] = 99
    assert session.apply_labels(edited)
    draft = session.snapshot()
    assert draft.parent_id == original.candidate_id and draft.edited and not draft.reviewed
    assert session.snapshot() is draft
    revision = draft.revision_id
    session.undo()
    assert not session.changed and session.can_redo
    np.testing.assert_array_equal(session.labels, original.result.output.labels)
    session.redo()
    assert session.changed and session.snapshot().revision_id == revision
    np.testing.assert_array_equal(session.labels, edited)
    assert session.snapshot().created_at == draft.created_at
    assert original.result.output.labels[0, 0] == 0 and original.reviewed
    restored = SegmentationEditSession.restore(original, session.snapshot())
    np.testing.assert_array_equal(restored.labels, edited)
    assert restored.changed and not restored.can_undo and not restored.can_redo
    assert restored.snapshot().candidate_id == draft.candidate_id


def test_new_operation_after_undo_discards_redo_and_noop_has_no_command():
    session = SegmentationEditSession(source())
    assert not session.apply_labels(session.labels)
    edited = session.labels.copy()
    edited[0, 0] = 42
    session.apply_labels(edited)
    session.undo()
    edited[0, 0] = 7
    session.apply_labels(edited)
    assert not session.can_redo
    session.undo()
    assert not session.changed


@pytest.mark.parametrize(
    "labels", [np.zeros((2, 2), dtype=int), np.ones((2, 3)), -np.ones((2, 3), dtype=int)]
)
def test_invalid_operation_is_atomic(labels):
    session = SegmentationEditSession(source())
    original = session.labels.copy()
    with pytest.raises(ValueError):
        session.apply_labels(labels)
    np.testing.assert_array_equal(session.labels, original)
    assert not session.changed and not session.can_undo


def test_renumbering_does_not_create_history_and_finish_can_preserve_requested_selection():
    original = source()
    session = SegmentationEditSession(original)
    renamed = np.where(session.labels == 42, 1, session.labels)
    session.apply_labels(renamed)
    assert session.changed and session.completed_candidate() is None
    history = SegmentationHistory("sample", recent_limit=1)
    history.add_candidate(original)
    session = SegmentationEditSession(original)
    edited = session.labels.copy()
    edited[0, 0] = 42
    session.apply_labels(edited)
    child = history.add_candidate(session.completed_candidate(), active_id=original.candidate_id)
    assert history.active is original
    assert child.edited and child.parent_id == original.candidate_id


def session_for(labels):
    return SegmentationEditSession(
        SegmentationCandidate.from_result(
            SegmentationResult(
                "sample",
                "stardist",
                ElementRef("data.h5", "/P"),
                SegmentationParameters(),
                SegmentationOutput(np.asarray(labels, dtype=np.uint32), "model", "1"),
            )
        )
    )


def test_outline_fills_interior_and_protects_other_segments():
    labels = np.zeros((10, 10), dtype=np.uint32)
    labels[3:6, 3:6] = 42
    session = session_for(labels)
    outline = [(1, 1), (1, 8), (8, 8), (8, 1)]
    preview = session.preview("draw", outline)
    assert not session.changed
    assert preview[2, 2] == 1 and preview[4, 4] == 42 and preview[0, 0] == 0
    assert session.edit("draw", outline)
    assert session.selected_ids == {1}
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)
    assert not session.can_undo
    assert session.edit("draw", outline, protect=False)
    assert session.labels[4, 4] == 1
    assert 42 not in session.areas[0]


def test_sparse_brush_events_have_no_gaps_and_use_integer_diameter():
    session = session_for(np.zeros((15, 20), dtype=np.uint32))
    session.apply_labels(np.pad(np.array([[42]], dtype=np.uint32), ((7, 7), (1, 18))))
    session.select(42)
    assert session.edit("add", [(7, 1), (7, 18)], size=5)
    assert np.all(session.labels[7, 1:19] == 42)
    assert session.labels[5, 10] == 42 and session.labels[4, 10] == 0
    session.undo()
    assert np.count_nonzero(session.labels) == 1
    assert not session.pending_disconnections


def test_removal_protection_and_sparse_id_deletion_are_atomic():
    labels = np.zeros((9, 9), dtype=np.uint32)
    labels[2:7, 1:4] = 42
    labels[2:7, 5:8] = 2**32 - 1
    session = session_for(labels)
    session.select(42)
    session.edit("remove", [(4, 0), (4, 8)], size=3, disconnected="keep")
    np.testing.assert_array_equal(session.labels[:, 5:8], labels[:, 5:8])
    session.undo()
    session.edit("remove", [(4, 0), (4, 8)], size=3, protect=False, disconnected="keep")
    assert not session.labels[4].any()
    session.undo()
    session.select(42)
    session.select(2**32 - 1, toggle=True)
    assert session.delete_selected()
    assert not session.labels.any()
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)


@pytest.mark.parametrize("policy", ["keep", "split", "ask"])
def test_disconnection_policy_is_part_of_the_single_stroke_command(policy):
    labels = np.full((7, 9), 42, dtype=np.uint32)
    session = session_for(labels)
    session.select(42)
    assert session.edit("remove", [(0, 4), (6, 4)], size=3, disconnected=policy)
    identities = set(map(int, session.areas[0]))
    assert identities == ({1, 42} if policy == "split" else {42})
    assert session.pending_disconnections == ({42} if policy == "ask" else set())
    after = session.labels.copy()
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)
    assert not session.can_undo and not session.pending_disconnections
    session.redo()
    np.testing.assert_array_equal(session.labels, after)
    assert session.pending_disconnections == ({42} if policy == "ask" else set())
    if policy == "split":
        assert np.all(session.labels[:, :3] == 42)  # Largest/tied first part retains its ID.


def test_pending_disconnections_heal_or_are_resolved_without_changing_source():
    labels = np.full((7, 9), 42, dtype=np.uint32)
    session = session_for(labels)
    session.select(42)
    session.edit("remove", [(0, 4), (6, 4)], size=3)
    assert session.pending_disconnections == {42}
    session.edit("add", [(3, 2), (3, 6)], size=3)
    assert not session.pending_disconnections
    session.undo()
    assert session.pending_disconnections == {42}
    session.resolve_disconnection(42, split=True)
    assert not session.pending_disconnections
    assert set(session.areas[0]) == {1, 42}
    session.undo()
    assert session.pending_disconnections == {42}
    session.resolve_disconnection(42, split=False)
    assert set(session.areas[0]) == {42} and not session.pending_disconnections
    np.testing.assert_array_equal(session.source.result.output.labels, labels)


def test_existing_disconnected_instances_are_not_asked_about_without_new_disconnection():
    session = session_for([[42, 0, 42], [0, 0, 0], [0, 0, 0]])
    session.select(42)
    session.edit("add", [(2, 0)], size=3, disconnected="ask")
    assert not session.pending_disconnections


def test_invalid_gesture_or_missing_target_leaves_labels_and_history_unchanged():
    session = session_for(np.zeros((5, 5), dtype=np.uint32))
    for args in (
        dict(tool="add", points=[(2, 2)]),
        dict(tool="remove", points=[(2, 2)]),
        dict(tool="draw", points=[(np.nan, 2), (1, 1), (2, 1)]),
        dict(tool="remove", points=[(2, 2)], protect=False, size=0),
    ):
        with pytest.raises(ValueError):
            session.edit(**args)
        assert not session.labels.any() and not session.can_undo and not session.changed
    assert not session.edit("draw", [(0, 0), (1, 1)])


@pytest.mark.parametrize("size", range(1, 9))
def test_brush_diameter_has_exact_integer_pixel_extent(size):
    session = session_for(np.zeros((20, 20), dtype=np.uint32))
    mask = session.brush_mask(session.labels.shape, np.array([[8.1, 8.2]]), size)
    ys, xs = np.nonzero(mask)
    assert np.ptp(ys) + 1 == size
    assert np.ptp(xs) + 1 == size
    if size in (1, 2):
        assert mask.sum() == size**2
    # Small subpixel movements do not change the snapped footprint.
    np.testing.assert_array_equal(
        mask, session.brush_mask(session.labels.shape, np.array([[8.3, 8.4]]), size)
    )


def test_outline_add_and_subtract_use_selected_instance_without_touching_protected_neighbors():
    labels = np.zeros((12, 12), dtype=np.uint32)
    labels[3:7, 3:7] = 42
    labels[3:7, 8:10] = 999
    session = session_for(labels)
    session.select(42)
    outline = [(2, 5), (2, 10), (8, 10), (8, 5)]
    assert session.edit("outline_add", outline)
    assert session.labels[4, 7] == 42
    assert session.labels[4, 8] == 999
    assert session.selected_ids == {42}
    assert len(session._undo) == 1
    assert session.edit("outline_remove", outline)
    assert session.labels[4, 5] == 0
    assert session.labels[4, 8] == 999
    session.undo()
    assert session.labels[4, 7] == 42
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)


def test_merge_keeps_largest_id_and_unrelated_pixels_and_is_one_undoable_command():
    labels = np.array([[7, 7, 0, 42, 42], [0, 0, 0, 42, 0], [999, 0, 0, 0, 0]], dtype=np.uint32)
    session = session_for(labels)
    session.select(7)
    session.select(42, toggle=True)
    assert session.merge_selected()
    expected = np.where(labels == 7, 42, labels)
    np.testing.assert_array_equal(session.labels, expected)
    assert session.selected_ids == {42} and not session.pending_disconnections
    assert len(session._undo) == 1
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)
    session.redo()
    np.testing.assert_array_equal(session.labels, expected)


def test_explicit_merge_can_intentionally_keep_disconnected_parts_together():
    session = session_for(np.full((7, 9), 42, dtype=np.uint32))
    session.select(42)
    session.edit("remove", [(0, 4), (6, 4)], size=3)
    assert session.pending_disconnections == {42}
    labels = session.labels.copy()
    labels[3, 4] = 7
    session.apply_labels(labels)
    session.select(7, toggle=True)
    before = session.labels.copy()
    assert session.merge_selected()
    assert not session.pending_disconnections
    assert session.part_count(42) > 1
    session.undo()
    np.testing.assert_array_equal(session.labels, before)
    assert session.pending_disconnections == {42}


@pytest.mark.parametrize(
    "points",
    [
        [(-1, 2), (5, 2)],
        [(2, -1), (2, 5)],
        [(-1, -1), (5, 5)],
        [(-1, 5), (5, -1)],
    ],
)
def test_dividing_strokes_preserve_area_and_ids_and_are_atomic(points):
    labels = np.zeros((7, 8), dtype=np.uint32)
    labels[:5, :5] = 42
    labels[6, 7] = 999
    session = session_for(labels)
    session.select(42)
    assert session.edit("split", points, disconnected="keep")
    np.testing.assert_array_equal(session.labels != 0, labels != 0)
    assert session.labels[6, 7] == 999
    assert session.selected_ids == {1, 42}
    assert not session.pending_disconnections and len(session._undo) == 1
    assert 42 in session.areas[0]
    after = session.labels.copy()
    session.undo()
    np.testing.assert_array_equal(session.labels, labels)
    session.redo()
    np.testing.assert_array_equal(session.labels, after)


def test_split_handles_small_regions_and_preserves_unrelated_diagonal_connections():
    labels = np.zeros((5, 6), dtype=np.uint32)
    labels[:3, :3] = 42
    labels[3, 3] = 42  # Connected only through a corner to the right-hand part.
    session = session_for(labels)
    session.select(42)
    session.split_selected([(-1, 1), (4, 1)])
    assert len(session.selected_ids) == 2
    assert session.labels[3, 3] == session.labels[2, 2]
    np.testing.assert_array_equal(session.labels > 0, labels > 0)


@pytest.mark.parametrize(
    "points",
    [[], [(2, 2)], [(2, 2), (2, 2)], [(1, 1), (2, 2)], [(0, 8), (6, 8)], [(np.nan, 1), (2, 2)]],
)
def test_unsuccessful_or_invalid_split_preserves_everything(points):
    session = session_for(np.full((5, 5), 42, dtype=np.uint32))
    session.select(42)
    before = session.labels.copy()
    revision = session.revision_id
    with pytest.raises(ValueError):
        session.split_selected(points)
    np.testing.assert_array_equal(session.labels, before)
    assert session.revision_id == revision
    assert not session.can_undo and not session.pending_disconnections
    assert session.selected_ids == {42}


def test_merge_and_split_require_the_right_selection():
    session = session_for([[7, 7, 42, 42]])
    with pytest.raises(ValueError):
        session.merge_selected()
    with pytest.raises(ValueError):
        session.split_selected([(0, 0), (0, 1)])
    session.select(7)
    with pytest.raises(ValueError):
        session.merge_selected()
    session.select(42, toggle=True)
    with pytest.raises(ValueError):
        session.split_selected([(0, 0), (0, 1)])
    assert not session.can_undo
