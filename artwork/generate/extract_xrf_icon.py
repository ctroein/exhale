#!/usr/bin/env python3
"""Extract the generated X artwork into reproducible icon-source variants."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

SOURCE_X_RECT = (11, 6, 20, 20)  # Inclusive x1, y1, x2, y2 in the 57-pixel mask.
GUIDE_RG_COLORS = ((230, 35, 0), (0, 190, 0), (218, 151, 18))
DARK_GREEN = (7, 31, 16)
RUNTIME_ICON = ROOT / "exhale" / "resources" / "icons" / "xrf.png"


def source_x_mask(source: np.ndarray) -> np.ndarray:
    """Return red-or-green X pixels from its clean source rectangle."""
    red_or_green = (source & 0b011) != 0
    x1, y1, x2, y2 = SOURCE_X_RECT
    mask = np.zeros_like(red_or_green)
    mask[y1 : y2 + 1, x1 : x2 + 1] = red_or_green[y1 : y2 + 1, x1 : x2 + 1]
    if not mask.any():
        raise ValueError(f"no source X pixels found in {SOURCE_X_RECT}")
    return mask


def fitted_x_mask(source: np.ndarray, guide: np.ndarray) -> np.ndarray:
    """Match the source X to its fitted red, green, and yellow guide components."""
    source_mask = source_x_mask(source)
    if guide.shape[0] != guide.shape[1] or source.shape[0] != source.shape[1]:
        raise ValueError("source mask and guide must be square")
    scaled_source = (
        np.asarray(
            Image.fromarray(source_mask.astype(np.uint8) * 255).resize(
                (guide.shape[1], guide.shape[0]),
                Image.Resampling.NEAREST,
            )
        )
        != 0
    )

    candidate = np.zeros(guide.shape[:2], dtype=bool)
    for color in GUIDE_RG_COLORS:
        candidate |= np.all(guide == color, axis=2)
    components, _ = label(candidate, structure=np.ones((3, 3), dtype=np.uint8))
    component_ids = np.unique(components[scaled_source & candidate])
    component_ids = component_ids[component_ids != 0]
    if not len(component_ids):
        raise ValueError("no fitted guide components overlap the source X")
    return np.isin(components, component_ids)


def expanded_masks(mask: np.ndarray, margin: float, feather: float) -> tuple[np.ndarray, ...]:
    """Return round-cornered core and outer masks plus the exterior blend weight."""
    if margin < 0 or feather < 0:
        raise ValueError("margin and feather must not be negative")
    distance = distance_transform_edt(~mask)
    core = distance <= margin
    outer = distance <= margin + feather
    blend = np.clip((margin + feather - distance) / max(feather, 1.0), 0.0, 1.0)
    blend[core] = 1.0
    blend = blend * blend * (3.0 - 2.0 * blend)
    return core, outer, blend


def square_crop_bounds(mask: np.ndarray, size: int) -> tuple[int, int, int, int]:
    """Return a centered fixed-size crop around the mask."""
    rows, columns = np.nonzero(mask)
    if not len(rows):
        raise ValueError("cannot crop an empty mask")
    center_x = int(columns.min() + columns.max() + 1) // 2
    center_y = int(rows.min() + rows.max() + 1) // 2
    left = center_x - size // 2
    upper = center_y - size // 2
    if left < 0 or upper < 0 or left + size > mask.shape[1] or upper + size > mask.shape[0]:
        raise ValueError("the centered icon crop extends beyond the image")
    return left, upper, left + size, upper + size


def extract_icon_sources(
    source_path: Path,
    guide_path: Path,
    image_path: Path,
    output_directory: Path,
    crop_size: int = 360,
    margin: float = 12.0,
    feather: float = 4.0,
    install_runtime: bool = False,
) -> tuple[Path, ...]:
    """Write the mask, diagnostic, transparent, and opaque icon sources."""
    with Image.open(source_path) as image:
        source = np.asarray(image).copy()
    with Image.open(guide_path) as image:
        guide = np.asarray(image.convert("RGB"))
    with Image.open(image_path) as image:
        generated = np.asarray(image.convert("RGB"))
    if generated.shape != guide.shape:
        raise ValueError("guide and generated image dimensions differ")

    fitted_mask = fitted_x_mask(source, guide)
    core_mask, _outer_mask, blend = expanded_masks(fitted_mask, margin, feather)
    bounds = square_crop_bounds(core_mask, crop_size)
    left, upper, right, lower = bounds
    cropped_mask = core_mask[upper:lower, left:right].copy()
    cropped_mask[[0, -1], :] = False
    cropped_mask[:, [0, -1]] = False
    cropped_blend = blend[upper:lower, left:right, None]
    cropped_image = generated[upper:lower, left:right]

    output_directory.mkdir(parents=True, exist_ok=True)
    mask_path = output_directory / "xrf_icon_x_mask.png"
    diagnostic_path = output_directory / "xrf_icon_x_region.png"
    transparent_path = output_directory / "xrf_icon_x_transparent.png"
    dark_path = output_directory / "xrf_icon_x_dark.png"

    Image.fromarray(cropped_mask.astype(np.uint8) * 255, "L").save(mask_path)

    dark_color = np.asarray(DARK_GREEN, dtype=np.float32)
    composited = np.round(
        cropped_image.astype(np.float32) * cropped_blend + dark_color * (1.0 - cropped_blend)
    ).astype(np.uint8)

    luminance = np.clip(
        0.2126 * cropped_image[..., 0]
        + 0.7152 * cropped_image[..., 1]
        + 0.0722 * cropped_image[..., 2],
        0,
        255,
    ).astype(np.uint8)
    diagnostic = np.repeat(luminance[..., None], 3, axis=2)
    diagnostic[cropped_mask] = composited[cropped_mask]
    Image.fromarray(diagnostic, "RGB").save(diagnostic_path)

    transparent = np.empty((*cropped_mask.shape, 4), dtype=np.uint8)
    transparent[..., :3] = composited
    transparent[..., 3] = cropped_mask.astype(np.uint8) * 255
    Image.fromarray(transparent, "RGBA").save(transparent_path)

    dark = np.empty_like(composited)
    dark[:] = DARK_GREEN
    dark[cropped_mask] = composited[cropped_mask]
    Image.fromarray(dark, "RGB").save(dark_path)

    if install_runtime:
        RUNTIME_ICON.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(transparent_path) as image:
            image.resize((512, 512), Image.Resampling.LANCZOS).save(RUNTIME_ICON)

    return mask_path, diagnostic_path, transparent_path, dark_path


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "57-masks.png")
    parser.add_argument("--guide", type=Path, default=HERE / "xrf_guide_57.png")
    parser.add_argument("--image", type=Path, default=HERE / "xrf_imagegen_57.png")
    parser.add_argument("--output-directory", type=Path, default=HERE)
    parser.add_argument("--crop-size", type=int, default=360)
    parser.add_argument("--margin", type=float, default=12.0)
    parser.add_argument("--feather", type=float, default=4.0)
    parser.add_argument(
        "--install-runtime",
        action="store_true",
        help="install the transparent 512-pixel application and Linux icon",
    )
    return parser


def main() -> None:
    args = parse_args().parse_args()
    paths = extract_icon_sources(
        args.source,
        args.guide,
        args.image,
        args.output_directory,
        args.crop_size,
        args.margin,
        args.feather,
        args.install_runtime,
    )
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
