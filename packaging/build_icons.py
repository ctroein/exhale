#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 21 10:43:55 2026

@author: carl
"""
#!/usr/bin/env python3

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image


ICONSET_SPECS: list[tuple[str, int]] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

ICO_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate .icns and .ico files from a single 1024x1024 PNG. "
            "Requires Pillow, plus either Apple's `iconutil` on macOS or "
            "`png2icns` on Linux for the .icns step.")
    )
    parser.add_argument("input_png", type=Path, help="Source PNG, ideally 1024x1024 RGBA")
    parser.add_argument(
        "-o",
        "--output-base",
        type=Path,
        default=None,
        help="Output base path without extension. Defaults to the input filename stem.",
    )
    parser.add_argument(
        "--keep-iconset",
        action="store_true",
        help="Keep the generated .iconset directory next to the outputs.",
    )
    return parser.parse_args()


def require_square_1024(img: Image.Image, path: Path) -> None:
    if img.size != (1024, 1024):
        raise ValueError(
            f"Expected a 1024x1024 PNG, got {img.size[0]}x{img.size[1]} for {path}"
        )


def load_rgba(path: Path) -> Image.Image:
    img = Image.open(path)
    require_square_1024(img, path)
    return img.convert("RGBA")


def save_iconset(img: Image.Image, iconset_dir: Path) -> None:
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for filename, size in ICONSET_SPECS:
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / filename)


def build_ico(img: Image.Image, out_path: Path) -> None:
    img.save(out_path, format="ICO", sizes=ICO_SIZES)



def build_icns(iconset_dir: Path, out_path: Path) -> str:
    try:
        from icnsutil import IcnsFile
    except ImportError as e:
        raise RuntimeError(
            "icnsutil is not installed. Run: pip install icnsutil"
        ) from e

    icns = IcnsFile()
    for filename, _size in ICONSET_SPECS:
        png_path = iconset_dir / filename
        icns.add_media(file=str(png_path))
    icns.write(str(out_path))


def main() -> int:
    args = parse_args()
    input_png = args.input_png.resolve()
    if not input_png.is_file():
        print(f"Input file not found: {input_png}", file=sys.stderr)
        return 2

    out_base = (args.output_base or input_png.with_suffix("")).resolve()
    out_base.parent.mkdir(parents=True, exist_ok=True)

    img = load_rgba(input_png)

    ico_path = out_base.with_suffix(".ico")
    icns_path = out_base.with_suffix(".icns")
    iconset_dir = out_base.with_suffix(".iconset")

    with tempfile.TemporaryDirectory(prefix="iconset-") as tmpdir:
        tmp_iconset = Path(tmpdir) / iconset_dir.name
        save_iconset(img, tmp_iconset)
        build_ico(img, ico_path)
        build_icns(tmp_iconset, icns_path)

        if args.keep_iconset:
            if iconset_dir.exists():
                shutil.rmtree(iconset_dir)
            shutil.copytree(tmp_iconset, iconset_dir)

    print(f"Wrote: {ico_path}")
    print(f"Wrote: {icns_path}")
    if not args.keep_iconset:
        print("Iconset directory not kept. Use --keep-iconset to save it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
