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

    _, _, _, merged, contacts, _ = guide.spline_mask(
        mask, 90, 1, 0, 0.5, 0.5, 1.0, 0.0
    )

    assert contacts > 0
    assert merged == 0


def test_sprinkled_yellow_points_are_isolated(tmp_path):
    sprinkle = _load_script("sprinkle_mask_points")
    source = np.zeros((20, 20), dtype=np.uint8)
    source[0, 0] = 2
    source_image = Image.fromarray(source, mode="P")
    source_image.putpalette([0, 0, 0] * 256)
    source_path = tmp_path / "source.png"
    output_path = tmp_path / "output.png"
    source_image.save(source_path)

    sprinkle.sprinkle_mask_points(source_path, output_path, 25, 20, 3)

    with Image.open(output_path) as image:
        bits = sprinkle._PALETTE_INDEX_TO_MASK_BITS[np.asarray(image)]
    assert np.count_nonzero(bits & 0b10) == 25
    assert np.count_nonzero(bits & 0b01) == 21
    for row, column in zip(*np.nonzero((bits & 0b01) != 0), strict=True):
        neighbourhood = bits[
            max(0, row - 1) : row + 2,
            max(0, column - 1) : column + 2,
        ]
        assert np.count_nonzero(neighbourhood & 0b01) == 1
