#!/usr/bin/env python3
"""Add deterministic blue and isolated yellow points to an indexed XRF mask."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "57-mask-y.png"
DEFAULT_OUTPUT = HERE / "57-masks.png"

# GIMP palette indices: background, overlap, yellow, blue.
_PALETTE_INDEX_TO_MASK_BITS = np.array((0b00, 0b11, 0b01, 0b10), dtype=np.uint8)
_MASK_BITS_TO_PALETTE_INDEX = np.array((0, 2, 3, 1), dtype=np.uint8)


def _isolated_yellow_candidates(mask_bits: np.ndarray, rng: np.random.Generator) -> list[int]:
    candidates = np.flatnonzero((mask_bits & 0b01) == 0)
    rng.shuffle(candidates)
    selected = []
    rows, columns = mask_bits.shape
    for flat_index in candidates:
        row, column = divmod(int(flat_index), columns)
        neighbourhood = mask_bits[
            max(0, row - 1) : min(rows, row + 2),
            max(0, column - 1) : min(columns, column + 2),
        ]
        if not np.any(neighbourhood & 0b01):
            selected.append(int(flat_index))
            mask_bits[row, column] |= 0b01
    return selected


def sprinkle_mask_points(
    source: Path,
    output: Path,
    blue_count: int,
    yellow_count: int,
    seed: int,
) -> None:
    """Add blue points and mutually non-neighbouring yellow points."""
    if blue_count < 0 or yellow_count < 0:
        raise ValueError("point counts must not be negative")
    with Image.open(source) as image:
        if image.mode != "P":
            raise ValueError(f"the source mask must be indexed, not {image.mode}")
        indices = np.asarray(image).copy()
        palette = image.getpalette()
        transparency = image.info.get("transparency")
    if indices.ndim != 2 or indices.size == 0:
        raise ValueError("the source mask must be a nonempty two-dimensional image")
    if int(indices.max()) >= len(_PALETTE_INDEX_TO_MASK_BITS):
        raise ValueError("the source mask must use only palette indices 0 through 3")

    mask_bits = _PALETTE_INDEX_TO_MASK_BITS[indices]
    rng = np.random.default_rng(seed)
    blue_candidates = np.flatnonzero((mask_bits & 0b10) == 0)
    if blue_count > len(blue_candidates):
        raise ValueError(
            f"cannot add {blue_count} blue points to only {len(blue_candidates)} pixels"
        )
    selected_blue = rng.choice(blue_candidates, size=blue_count, replace=False)
    mask_bits.flat[selected_blue] |= 0b10

    selected_yellow = _isolated_yellow_candidates(mask_bits, rng)
    if yellow_count > len(selected_yellow):
        raise ValueError(
            f"cannot add {yellow_count} isolated yellow points; "
            f"only {len(selected_yellow)} positions are available"
        )
    # The helper marks every candidate while constructing an independent set.
    # Retain only the requested prefix.
    mask_bits &= 0b10
    mask_bits |= _PALETTE_INDEX_TO_MASK_BITS[indices] & 0b01
    mask_bits.flat[selected_yellow[:yellow_count]] |= 0b01

    result = Image.fromarray(_MASK_BITS_TO_PALETTE_INDEX[mask_bits], mode="P")
    result.putpalette(palette)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_options = {} if transparency is None else {"transparency": transparency}
    result.save(output, **save_options)


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Add deterministic points to an indexed XRF mask.")
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_SOURCE)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--blue-count", type=int, default=100)
    parser.add_argument("--yellow-count", type=int, default=40)
    parser.add_argument("--seed", type=int, default=5700)
    return parser


def main() -> None:
    args = parse_args().parse_args()
    sprinkle_mask_points(
        args.source,
        args.output,
        args.blue_count,
        args.yellow_count,
        args.seed,
    )
    print(args.output)


if __name__ == "__main__":
    main()
