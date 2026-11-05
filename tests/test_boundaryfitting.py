"""Boundary recovery, hard displacement limits and deterministic calibration splits."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import ndimage as ndi

from exhale.analysis.boundarycalibration import (
    boundary_scores,
    calibrate_boundaries,
    make_boundary_cases,
)
from exhale.analysis.boundaryfitting import BoundaryFitParameters, fit_boundary


def circle():
    y, x = np.mgrid[:60, :60]
    target = (y - 30) ** 2 + (x - 30) ** 2 <= 100
    initial = (y - 30) ** 2 + (x - 30) ** 2 <= 169
    return ndi.gaussian_filter(target.astype(float), 0.8), target, initial


@pytest.mark.parametrize("method", ["edges", "region"])
def test_fit_recovers_a_clear_boundary_without_changing_inputs(method):
    image, target, initial = circle()
    before_image, before_initial = image.copy(), initial.copy()
    settings = BoundaryFitParameters(method=method, iterations=30, max_distance=5, balloon=-1)
    fitted = fit_boundary(image, initial, settings)
    assert fitted.dtype == bool and fitted.shape == image.shape
    assert boundary_scores(fitted, target)["iou"] > 0.95
    assert boundary_scores(fitted, target)["iou"] > boundary_scores(initial, target)["iou"]
    np.testing.assert_array_equal(image, before_image)
    np.testing.assert_array_equal(initial, before_initial)


@pytest.mark.parametrize("method", ["edges", "region"])
def test_fit_is_independent_of_previous_calls_and_respects_limits_and_protection(method):
    image, target, initial = circle()
    protected = np.zeros(image.shape, bool)
    protected[28:32, 28:32] = True
    settings = BoundaryFitParameters(method=method, iterations=7, max_distance=2, balloon=1)
    first = fit_boundary(image, initial, settings, protected=protected)
    fit_boundary(image, target, replace(settings, iterations=3))
    second = fit_boundary(image, initial, settings, protected=protected)
    np.testing.assert_array_equal(first, second)
    assert not first[protected].any()
    assert not first[ndi.distance_transform_edt(~initial) > 2].any()
    core = ndi.distance_transform_edt(initial) > 2
    assert first[core & ~protected].all()


def test_uninformative_image_keeps_initial_outline_and_invalid_data_is_reported():
    image, _target, initial = circle()
    np.testing.assert_array_equal(fit_boundary(np.ones(image.shape), initial), initial)
    with pytest.raises(ValueError, match="finite"):
        fit_boundary(np.full(image.shape, np.nan), initial)
    with pytest.raises(ValueError, match="matching"):
        fit_boundary(image, initial[:2])
    with pytest.raises(ValueError, match="unprotected"):
        fit_boundary(image, np.zeros(image.shape, bool))


@pytest.mark.parametrize(
    "kwargs", [{"iterations": 0}, {"sigma": 0}, {"max_distance": -1}, {"method": "unknown"}]
)
def test_invalid_settings_fail_before_fitting(kwargs):
    with pytest.raises(ValueError):
        BoundaryFitParameters(**kwargs)


def maps():
    y, x = np.mgrid[:70, :70]
    labels = np.zeros(y.shape, np.uint32)
    for identity, (cy, cx) in enumerate(((15, 15), (15, 48), (48, 15), (48, 48)), start=1):
        labels[(y - cy) ** 2 + (x - cx) ** 2 <= 36] = identity
    return ndi.gaussian_filter((labels > 0).astype(float), 0.8), labels


def test_perturbations_are_reproducible_and_segments_never_leak_into_holdout():
    image, labels = maps()
    cases, selection = make_boundary_cases(image, labels, "sample", seed=12)
    again, selection_again = make_boundary_cases(image, labels, "sample", seed=12)
    assert selection == selection_again
    assert {case.variant for case in cases} == {"expanded", "contracted", "shifted", "distorted"}
    train = {case.segment_id for case in cases if case.split == "train"}
    validation = {case.segment_id for case in cases if case.split == "validation"}
    assert train and validation and not train & validation
    for case, repeated in zip(cases, again, strict=True):
        assert case.key == repeated.key
        np.testing.assert_array_equal(case.initial, repeated.initial)
        assert not np.array_equal(case.initial, case.target)


def test_holdout_targets_cannot_influence_parameter_selection():
    image, labels = maps()
    cases, _selection = make_boundary_cases(image, labels, "sample", max_segments=3)
    parameters = [BoundaryFitParameters(iterations=2), BoundaryFitParameters(iterations=2, sigma=2)]
    original = calibrate_boundaries(cases, parameters)
    altered = [
        replace(case, target=np.ones(case.target.shape, bool))
        if case.split == "validation"
        else case
        for case in cases
    ]
    repeated = calibrate_boundaries(altered, parameters)
    assert original["best"] == repeated["best"]
    assert [row for row in original["scores"] if row["split"] == "train"] == [
        row for row in repeated["scores"] if row["split"] == "train"
    ]
    with pytest.raises(ValueError, match="both groups"):
        calibrate_boundaries(
            [
                *cases,
                replace(
                    cases[0], split="train" if cases[0].split == "validation" else "validation"
                ),
            ],
            parameters,
        )


def test_boundary_score_reports_identity_and_empty_prediction():
    _image, target, _initial = circle()
    assert boundary_scores(target, target) == {
        "iou": 1.0,
        "boundary_distance_px": 0.0,
        "empty": False,
    }
    empty = boundary_scores(np.zeros(target.shape, bool), target)
    assert empty["iou"] == 0 and empty["empty"]
    assert np.isfinite(empty["boundary_distance_px"])
