#!/usr/bin/env python3
"""Add deterministic blue and magenta spots to an indexed XRF mask."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "57-mask-y.png"
DEFAULT_OUTPUT = HERE / "57-masks.png"

# Palette indices are RGB bit fields: bit 0 = red, bit 1 = green, bit 2 = blue.
_BLUE_BIT = 0b100
_MAGENTA_BITS = 0b101
_PALETTE = (
    (0, 80, 0),
    (230, 35, 0),
    (0, 190, 0),
    (255, 255, 0),
    (0, 0, 255),
    (210, 30, 230),
    (0, 200, 220),
    (180, 235, 150),
)


def sprinkle_mask_points(
    source: Path,
    output: Path,
    blue_spot_count: int,
    magenta_spot_count: int,
    maximum_length: int,
    seed: int,
) -> list[tuple[int, list[tuple[int, int]]]]:
    """Add random-walk spots and thin green from RG interiors."""
    if blue_spot_count < 0 or magenta_spot_count < 0:
        raise ValueError("spot counts must not be negative")
    if maximum_length < 1:
        raise ValueError("the maximum spot length must be positive")
    with Image.open(source) as image:
        if image.mode != "P":
            raise ValueError(f"the source mask must be indexed, not {image.mode}")
        indices = np.asarray(image).copy()
        transparency = image.info.get("transparency")
    if indices.ndim != 2 or indices.size == 0:
        raise ValueError("the source mask must be a nonempty two-dimensional image")
    if int(indices.max()) >= len(_PALETTE):
        raise ValueError("the source mask must use only palette indices 0 through 7")

    mask_bits = indices
    rng = np.random.default_rng(seed)
    rows, columns = mask_bits.shape
    directions = ((-1, 0), (0, 1), (1, 0), (0, -1))
    walks = []
    for bits, spot_count, color_name, stop_on_collision in (
        (_BLUE_BIT, blue_spot_count, "blue", False),
        (_MAGENTA_BITS, magenta_spot_count, "magenta", True),
    ):
        for _ in range(spot_count):
            occupied = mask_bits != 0
            unavailable = np.pad(occupied, 1)
            unavailable = np.logical_or.reduce(
                [
                    unavailable[dr : dr + rows, dc : dc + columns]
                    for dr in range(3)
                    for dc in range(3)
                ]
            )
            candidates = np.flatnonzero(~unavailable)
            if not len(candidates):
                raise ValueError(f"cannot place all {spot_count} {color_name} spots")
            start = int(rng.choice(candidates))
            row, column = divmod(start, columns)
            mask_bits[row, column] = bits
            walk = [(row, column)]
            for _ in range(maximum_length - 1):
                dr, dc = directions[int(rng.integers(len(directions)))]
                row += dr
                column += dc
                if not (0 <= row < rows and 0 <= column < columns):
                    break
                if stop_on_collision and mask_bits[row, column] & bits == bits:
                    break
                mask_bits[row, column] |= bits
                walk.append((row, column))
            walks.append((bits, walk))

    red_and_green = (mask_bits & 0b011) == 0b011
    neighbor_count = np.zeros(mask_bits.shape, dtype=np.uint8)
    neighbor_count[1:] += red_and_green[:-1]
    neighbor_count[:-1] += red_and_green[1:]
    neighbor_count[:, 1:] += red_and_green[:, :-1]
    neighbor_count[:, :-1] += red_and_green[:, 1:]
    remove_green = red_and_green & (neighbor_count >= 3)
    mask_bits[remove_green] &= 0b101

    result = Image.fromarray(mask_bits, mode="P")
    result.putpalette([channel for color in _PALETTE for channel in color])
    output.parent.mkdir(parents=True, exist_ok=True)
    save_options = {} if transparency is None else {"transparency": transparency}
    result.save(output, **save_options)
    return walks


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Add deterministic color spots to an indexed XRF mask.")
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_SOURCE)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--blue-spot-count", type=int, default=75)
    parser.add_argument("--magenta-spot-count", type=int, default=10)
    parser.add_argument("--maximum-length", type=int, default=6)
    parser.add_argument("--seed", type=int, default=5700)
    return parser


def main() -> None:
    args = parse_args().parse_args()
    sprinkle_mask_points(
        args.source,
        args.output,
        args.blue_spot_count,
        args.magenta_spot_count,
        args.maximum_length,
        args.seed,
    )
    print(args.output)


if __name__ == "__main__":
    main()
