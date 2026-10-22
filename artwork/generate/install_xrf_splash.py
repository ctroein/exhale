#!/usr/bin/env python3
"""Install selected XRF artwork as the application's fixed-size splash image."""

from argparse import ArgumentParser
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME_SPLASH = ROOT / "exhale" / "resources" / "xrf_splash.jpg"
SPLASH_SIZE = 627


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("input_artwork", type=Path)
    args = parser.parse_args()
    with Image.open(args.input_artwork) as source:
        splash = source.convert("RGB").resize((SPLASH_SIZE, SPLASH_SIZE), Image.Resampling.LANCZOS)
    RUNTIME_SPLASH.parent.mkdir(parents=True, exist_ok=True)
    splash.save(RUNTIME_SPLASH, quality=95)
    print(RUNTIME_SPLASH)


if __name__ == "__main__":
    main()
