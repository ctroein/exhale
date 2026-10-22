#!/usr/bin/env python3
"""Install selected XRF artwork as the application's fixed-size splash image."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME_SPLASH = ROOT / "exhale" / "resources" / "xrf_splash.jpg"
SPLASH_SIZE = 627
STATUS_HEIGHT = 28
STATUS_FEATHER = 8
STATUS_MAXIMUM_BRIGHTNESS = 64  # 25% on the 0–255 HSB brightness scale.


def darken_status_area(image: Image.Image) -> Image.Image:
    """Darken the full-width status strip with a smooth transition above it."""
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    height = pixels.shape[0]
    if height < STATUS_HEIGHT + STATUS_FEATHER:
        raise ValueError("the splash is too small for the configured status area")

    region = pixels[-(STATUS_HEIGHT + STATUS_FEATHER) :, :]
    maximum = region.max(axis=2, keepdims=True)
    darkened = region * np.minimum(
        1.0,
        STATUS_MAXIMUM_BRIGHTNESS / np.maximum(maximum, 1.0),
    )

    from_bottom = np.arange(STATUS_HEIGHT + STATUS_FEATHER - 1, -1, -1, dtype=np.float32)
    vertical = np.clip(
        (STATUS_HEIGHT + STATUS_FEATHER - 1 - from_bottom) / STATUS_FEATHER,
        0.0,
        1.0,
    )
    blend = vertical[:, None]
    blend = blend * blend * (3.0 - 2.0 * blend)
    region[:] = region * (1.0 - blend[..., None]) + darkened * blend[..., None]
    return Image.fromarray(np.round(pixels).astype(np.uint8), "RGB")


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("input_artwork", type=Path)
    args = parser.parse_args()
    with Image.open(args.input_artwork) as source:
        splash = source.convert("RGB").resize((SPLASH_SIZE, SPLASH_SIZE), Image.Resampling.LANCZOS)
    splash = darken_status_area(splash)
    RUNTIME_SPLASH.parent.mkdir(parents=True, exist_ok=True)
    splash.save(RUNTIME_SPLASH, quality=95, subsampling=0)
    print(RUNTIME_SPLASH)


if __name__ == "__main__":
    main()
