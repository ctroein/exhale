"""Directional outline fitting preserves topology, locality and bright object borders."""

import numpy as np
import pytest
from scipy import ndimage as ndi

from exhale.analysis.boundarycalibration import boundary_scores
from exhale.analysis.boundaryfitting import _closed_displacements, _mask_topology, fit_outline


def bright_disc():
    y, x = np.mgrid[:80, :80]
    target = (y - 40) ** 2 + (x - 40) ** 2 <= 12**2
    return ndi.gaussian_filter(target.astype(float), 0.8), target, y, x


@pytest.mark.parametrize("radius", [9, 14, 18])
def test_enlarges_or_reduces_an_approximate_outline_toward_the_boundary(radius):
    image, target, y, x = bright_disc()
    initial = (y - 40) ** 2 + (x - 40) ** 2 <= radius**2
    image_before, mask_before = image.copy(), initial.copy()
    result = fit_outline(image, initial)
    assert boundary_scores(result, target)["iou"] > 0.85
    assert boundary_scores(result, target)["iou"] > boundary_scores(initial, target)["iou"]
    assert _mask_topology(result) == (1, 0)
    np.testing.assert_array_equal(image, image_before)
    np.testing.assert_array_equal(initial, mask_before)


def test_bright_internal_spots_do_not_collapse_the_enclosing_outline():
    image, target, y, x = bright_disc()
    initial = (y - 40) ** 2 + (x - 40) ** 2 <= 14**2
    for cy, cx in ((38, 38), (43, 43)):
        image += 20 * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / 1.5)
    result = fit_outline(image, initial)
    assert boundary_scores(result, target)["iou"] > 0.9
    assert result.sum() >= 0.85 * target.sum()
    assert _mask_topology(result) == (1, 0)


def test_wrong_polarity_edges_do_not_attract_a_bright_inside_outline():
    image, _, y, x = bright_disc()
    initial = (y - 40) ** 2 + (x - 40) ** 2 <= 14**2
    result = fit_outline(1 - image, initial)
    np.testing.assert_array_equal(result, initial)


def test_limits_protected_pixels_and_determinism():
    image, _, y, x = bright_disc()
    initial = (y - 40) ** 2 + (x - 40) ** 2 <= 18**2
    protected = np.zeros(initial.shape, bool)
    protected[39:42, 39:42] = True
    before = protected.copy()
    result = fit_outline(image, initial, max_distance=3, protected=protected)
    fit_outline(image, initial, max_distance=5)
    np.testing.assert_array_equal(
        result, fit_outline(image, initial, max_distance=3, protected=protected)
    )
    assert not result[protected].any()
    seed = initial & ~protected
    assert not result[ndi.distance_transform_edt(~seed) > 3].any()
    core = ndi.distance_transform_edt(seed) > 3
    assert result[core].all()
    assert _mask_topology(result) == _mask_topology(seed)
    np.testing.assert_array_equal(protected, before)


def test_multiple_components_and_inner_holes_are_retained():
    y, x = np.mgrid[:95, :95]
    target = ((y - 28) ** 2 + (x - 28) ** 2 <= 12**2) & ((y - 28) ** 2 + (x - 28) ** 2 >= 5**2)
    target |= (y - 67) ** 2 + (x - 67) ** 2 <= 9**2
    initial = ndi.binary_dilation(target, iterations=2)
    image = ndi.gaussian_filter(target.astype(float), 1)
    result = fit_outline(image, initial, max_distance=4)
    assert _mask_topology(result) == _mask_topology(initial) == (2, 1)
    assert boundary_scores(result, target)["iou"] > 0.8


def test_empty_image_preserves_the_drawing_and_nonfinite_values_are_handled():
    image, initial, _, _ = bright_disc()
    np.testing.assert_array_equal(fit_outline(np.zeros(image.shape), initial), initial)
    image[5, 5] = np.nan
    result = fit_outline(image, initial)
    assert result.dtype == bool and _mask_topology(result) == (1, 0)
    with pytest.raises(ValueError, match="finite"):
        fit_outline(np.full(image.shape, np.nan), initial)


@pytest.mark.parametrize("distance", [0, -1, np.nan, np.inf])
def test_invalid_adjustment_distance_is_rejected(distance):
    image, initial, _, _ = bright_disc()
    with pytest.raises(ValueError, match="distance"):
        fit_outline(image, initial, max_distance=distance)


def test_invalid_shapes_and_empty_unprotected_region_are_rejected():
    image, initial, _, _ = bright_disc()
    with pytest.raises(ValueError, match="matching"):
        fit_outline(image, initial[:2])
    with pytest.raises(ValueError, match="Protected"):
        fit_outline(image, initial, protected=np.zeros((2, 2)))
    with pytest.raises(ValueError, match="unprotected"):
        fit_outline(image, initial, protected=initial)


def test_cyclic_displacement_has_no_arbitrary_start_point_seam():
    rng = np.random.default_rng(5)
    offsets = np.linspace(-2, 2, 9)
    cost = rng.normal(size=(24, len(offsets)))
    original = _closed_displacements(cost, offsets)
    shifted = _closed_displacements(np.roll(cost, 7, axis=0), offsets)
    np.testing.assert_allclose(shifted, np.roll(original, 7), atol=1e-10)
