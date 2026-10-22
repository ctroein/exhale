import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

GENERATORS = Path(__file__).parents[1] / "artwork" / "generate"


def _load_script(name: str):
    path = GENERATORS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spline_mask_preserves_enclosed_hole():
    guide = _load_script("generate_xrf_guide")
    mask = np.zeros((9, 9), dtype=bool)
    mask[1:8, 1:8] = True
    mask[3:6, 3:6] = False

    result, *_ = guide.spline_mask(mask, 90, 1, 0, 0.5, 0.5, 1.0, 0.0)

    assert result[20, 20]
    assert not result[45, 45]


def test_diagonal_contact_with_large_component_remains_separate():
    guide = _load_script("generate_xrf_guide")
    mask = np.zeros((9, 9), dtype=bool)
    mask[1:3, 1:4] = True
    mask[3, 4] = True

    _, _, _, merged, contacts, _ = guide.spline_mask(mask, 90, 1, 0, 0.5, 0.5, 1.0, 0.0)

    assert contacts > 0
    assert merged == 0


def test_sprinkling_adds_only_blue_random_walks(tmp_path):
    sprinkle = _load_script("sprinkle_mask_points")
    source = np.zeros((20, 20), dtype=np.uint8)
    source[0, 0] = 3
    source_image = Image.fromarray(source, mode="P")
    source_image.putpalette([0, 0, 0] * 256)
    source_path = tmp_path / "source.png"
    output_path = tmp_path / "output.png"
    source_image.save(source_path)

    walks = sprinkle.sprinkle_mask_points(source_path, output_path, 5, 3, 6, 3)

    with Image.open(output_path) as image:
        bits = np.asarray(image)
    assert 5 <= np.count_nonzero(bits == 0b100) <= 30
    assert 3 <= np.count_nonzero((bits & 0b101) == 0b101) <= 18
    assert np.count_nonzero((bits & 0b011) == 0b011) == 1
    occupied = source != 0
    for channel_bits, walk in walks:
        start_row, start_column = walk[0]
        assert start_row < source.shape[0] - 3
        assert not occupied[
            max(0, start_row - 1) : start_row + 2,
            max(0, start_column - 1) : start_column + 2,
        ].any()
        assert 1 <= len(walk) <= 6
        for first, second in zip(walk, walk[1:], strict=False):
            assert abs(first[0] - second[0]) + abs(first[1] - second[1]) == 1
        for row, column in walk:
            occupied[row, column] = True
            assert bits[row, column] & channel_bits == channel_bits


def test_dense_rg_pixels_lose_green(tmp_path):
    sprinkle = _load_script("sprinkle_mask_points")
    source = np.zeros((5, 5), dtype=np.uint8)
    source[1:4, 1:4] = 0b011
    source_image = Image.fromarray(source, mode="P")
    source_image.putpalette([0, 0, 0] * 256)
    source_path = tmp_path / "source.png"
    output_path = tmp_path / "output.png"
    source_image.save(source_path)

    sprinkle.sprinkle_mask_points(source_path, output_path, 0, 0, 6, 3)

    with Image.open(output_path) as image:
        result = np.asarray(image)
    assert result[2, 2] == 0b001
    assert np.all(result[(1, 1, 3, 3), (1, 3, 1, 3)] == 0b011)


def test_spot_colors_are_fixed_per_connected_region():
    guide = _load_script("generate_xrf_guide")
    bits = np.zeros((40, 40), dtype=np.uint8)
    bits[:, :20] = 0b100
    bits[:, 20:] = 0b101
    colors = np.zeros((8, 3), dtype=np.uint8)

    first = guide.categorical_spot_colors(bits, colors, 12)
    second = guide.categorical_spot_colors(bits, colors, 12)

    assert np.array_equal(first, second)
    assert np.array_equal(np.unique(first[:, :20].reshape(-1, 3), axis=0), ((107, 125, 58),))
    assert np.array_equal(np.unique(first[:, 20:].reshape(-1, 3), axis=0), ((96, 112, 176),))

    separate = np.zeros((25, 25), dtype=np.uint8)
    positions = [(2 + 5 * row, 2 + 5 * column) for row in range(2) for column in range(4)]
    for position in positions:
        separate[position] = 0b101
    separate_colors = guide.categorical_spot_colors(separate, colors, 12)
    assigned = [tuple(separate_colors[position]) for position in positions]
    assert assigned.count((96, 112, 176)) == 7
    assert assigned.count((145, 105, 125)) == 1
    assert assigned[-1] == (96, 112, 176)


def test_x_icon_extraction_uses_only_pixels_in_the_clean_source_rectangle():
    icon = _load_script("extract_xrf_icon")
    source = np.zeros((57, 57), dtype=np.uint8)
    source[6:21, 11:21] = 0b011
    source[9:24, 22:26] = 0b011
    guide = np.zeros((114, 114, 3), dtype=np.uint8)
    guide[18:48, 22:42] = (218, 151, 18)
    guide[18:48, 44:52] = (218, 151, 18)

    mask = icon.fitted_x_mask(source, guide)

    assert mask[20, 30]
    assert not mask[20, 46]


def test_x_icon_expansion_has_rounded_mask_and_feathered_color_weight():
    icon = _load_script("extract_xrf_icon")
    mask = np.zeros((31, 31), dtype=bool)
    mask[15, 15] = True

    core, outer, blend = icon.expanded_masks(mask, margin=3, feather=2)

    assert core[15, 18]
    assert not core[18, 18]
    assert outer[15, 20]
    assert not outer[19, 19]
    assert blend[15, 18] == 1.0
    assert 0.0 < blend[15, 19] < 1.0
    assert blend[15, 20] == 0.0


def test_x_icon_crop_is_fixed_and_contains_the_mask():
    icon = _load_script("extract_xrf_icon")
    mask = np.zeros((100, 100), dtype=bool)
    mask[30:70, 35:65] = True

    assert icon.square_crop_bounds(mask, 60) == (20, 20, 80, 80)


def test_splash_status_area_is_dark_with_smooth_transition():
    splash = _load_script("install_xrf_splash")
    image = Image.new("RGB", (240, 80), (200, 100, 50))

    result = np.asarray(splash.darken_status_area(image))

    assert result[-1, 0].max() <= splash.STATUS_MAXIMUM_BRIGHTNESS
    assert result[-splash.STATUS_HEIGHT, -1].max() <= splash.STATUS_MAXIMUM_BRIGHTNESS
    assert result[-1, -1].max() <= splash.STATUS_MAXIMUM_BRIGHTNESS
    assert splash.STATUS_MAXIMUM_BRIGHTNESS < result[-splash.STATUS_HEIGHT - 1, 0].max() < 200
    assert np.array_equal(result[-1, 0], (64, 32, 16))
    assert np.array_equal(result[0, 0], (200, 100, 50))
