#!/usr/bin/env python3
"""Apply a feathered XRF-guide foreground as an artwork alpha channel."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GUIDE_FOREGROUND_COLORS = np.array(((218, 151, 18), (16, 91, 198)), dtype=np.uint8)
RUNTIME_LOGO = ROOT / "exhale" / "resources" / "icons" / "xrf.png"
RUNTIME_SPLASH = ROOT / "exhale" / "resources" / "xrf_splash.jpg"
PACKAGING_LOGO_SOURCE = ROOT / "artwork" / "logos" / "xrf_cells_1024.png"
SPLASH_SIZE = 627


def guide_foreground(guide: Image.Image, size: int) -> np.ndarray:
    """Return the yellow-or-blue guide foreground at the requested size."""
    guide = guide.convert("RGB")
    if guide.size != (size, size):
        guide = guide.resize((size, size), Image.Resampling.NEAREST)
    pixels = np.asarray(guide)
    return np.any(np.all(pixels[:, :, None, :] == GUIDE_FOREGROUND_COLORS, axis=3), axis=2)


def feathered_alpha(
    foreground: np.ndarray,
    opaque_radius: float,
    feather_radius: float,
) -> np.ndarray:
    """Grow foreground opaquely, then add a smooth outward feather."""
    if opaque_radius < 0 or feather_radius < 0:
        raise ValueError("the opaque and feather radii must not be negative")

    distance = distance_transform_edt(~foreground)
    if feather_radius == 0:
        opacity = distance <= opaque_radius
    else:
        opacity = np.clip(1.0 - (distance - opaque_radius) / feather_radius, 0.0, 1.0)
        opacity = opacity * opacity * (3.0 - 2.0 * opacity)
        opacity[distance <= opaque_radius] = 1.0
    return np.round(opacity * 255).astype(np.uint8)


def intensity_alpha(
    image: Image.Image,
    minimum: float,
    maximum: float,
    opaque_percentile: float,
    sample_mask: np.ndarray,
) -> np.ndarray:
    """Map luminance to alpha, saturating at a sampled intensity percentile."""
    if not 0.0 <= minimum <= maximum <= 1.0:
        raise ValueError("background alpha limits must satisfy 0 <= minimum <= maximum <= 1")
    if not 0.0 <= opaque_percentile <= 100.0:
        raise ValueError("the opaque-background percentile must be between 0 and 100")
    pixels = np.asarray(image, dtype=np.float32) / 255.0
    luminance = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    sampled_luminance = luminance[sample_mask]
    if sampled_luminance.size == 0:
        raise ValueError("the guide leaves no background pixels for intensity sampling")
    opaque_intensity = float(np.percentile(sampled_luminance, opaque_percentile))
    scaled_luminance = np.clip(luminance / max(opaque_intensity, 1e-9), 0.0, 1.0)
    opacity = minimum + scaled_luminance * (maximum - minimum)
    return np.round(opacity * 255).astype(np.uint8)


def fade_image_edges(alpha: np.ndarray, radius: float) -> np.ndarray:
    """Fade an alpha channel smoothly to zero at every image edge."""
    if radius < 0:
        raise ValueError("the edge-fade radius must not be negative")
    if radius == 0:
        return alpha

    rows, columns = alpha.shape
    y, x = np.ogrid[:rows, :columns]
    edge_distance = np.minimum.reduce(
        (
            np.broadcast_to(y, alpha.shape),
            np.broadcast_to(x, alpha.shape),
            np.broadcast_to(rows - 1 - y, alpha.shape),
            np.broadcast_to(columns - 1 - x, alpha.shape),
        )
    )
    opacity = np.clip(edge_distance / radius, 0.0, 1.0)
    opacity = opacity * opacity * (3.0 - 2.0 * opacity)
    return np.round(alpha.astype(np.float32) * opacity).astype(np.uint8)


def compose_guide_alpha(
    input_logo: Path,
    guide_path: Path,
    *,
    size: int = 512,
    opaque_radius: float = 0.0,
    feather_radius: float = 8.0,
    background_alpha_minimum: float = 0.1,
    background_alpha_maximum: float = 0.8,
    background_opaque_percentile: float = 95.0,
    edge_fade_radius: float = 5.0,
) -> Image.Image:
    """Return resized artwork with combined intensity and guide-derived alpha."""
    if size <= 0:
        raise ValueError("the output size must be positive")
    with Image.open(guide_path) as guide:
        foreground = guide_foreground(guide, size)
    with Image.open(input_logo) as source:
        logo = source.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    result = logo.convert("RGBA")
    cell_alpha = feathered_alpha(foreground, opaque_radius, feather_radius)
    background_alpha = intensity_alpha(
        logo,
        background_alpha_minimum,
        background_alpha_maximum,
        background_opaque_percentile,
        cell_alpha == 0,
    )
    alpha = np.maximum(cell_alpha, background_alpha)
    alpha = fade_image_edges(alpha, edge_fade_radius)
    result.putalpha(Image.fromarray(alpha, mode="L"))
    return result


def apply_guide_alpha(
    input_logo: Path,
    guide_path: Path,
    output: Path,
    **options,
) -> None:
    """Compose an alpha-masked inspection candidate and save it."""
    result = compose_guide_alpha(input_logo, guide_path, **options)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)


def install_icon_assets(
    input_logo: Path,
    guide_path: Path,
    candidate: Path,
    *,
    size: int,
    opaque_radius: float,
    feather_radius: float,
    background_alpha_minimum: float,
    background_alpha_maximum: float,
    background_opaque_percentile: float,
    edge_fade_radius: float,
) -> None:
    """Install an inspected candidate as runtime and packaging icon sources."""
    with Image.open(candidate) as source:
        runtime_logo = source.copy()

    scale = 1024 / size
    packaging_logo = compose_guide_alpha(
        input_logo,
        guide_path,
        size=1024,
        opaque_radius=opaque_radius * scale,
        feather_radius=feather_radius * scale,
        background_alpha_minimum=background_alpha_minimum,
        background_alpha_maximum=background_alpha_maximum,
        background_opaque_percentile=background_opaque_percentile,
        edge_fade_radius=edge_fade_radius * scale,
    )
    for destination in (RUNTIME_LOGO, PACKAGING_LOGO_SOURCE):
        destination.parent.mkdir(parents=True, exist_ok=True)
    runtime_logo.save(RUNTIME_LOGO)
    packaging_logo.save(PACKAGING_LOGO_SOURCE)


def install_splash(input_artwork: Path) -> None:
    """Install RGB artwork at the application's fixed splash size."""
    with Image.open(input_artwork) as source:
        splash = source.convert("RGB").resize(
            (SPLASH_SIZE, SPLASH_SIZE), Image.Resampling.LANCZOS
        )
    RUNTIME_SPLASH.parent.mkdir(parents=True, exist_ok=True)
    splash.save(RUNTIME_SPLASH, quality=95)


def parse_args():
    parser = ArgumentParser(
        description="Resize XRF artwork and apply a feathered alpha mask from the guide."
    )
    parser.add_argument("input_logo", type=Path)
    parser.add_argument(
        "-g",
        "--guide",
        type=Path,
        default=HERE / "xrf_guide.png",
    )
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--opaque-radius", type=float, default=0.0)
    parser.add_argument("--feather-radius", type=float, default=8.0)
    parser.add_argument("--background-alpha-minimum", type=float, default=0.1)
    parser.add_argument("--background-alpha-maximum", type=float, default=0.8)
    parser.add_argument("--background-opaque-percentile", type=float, default=95.0)
    parser.add_argument("--edge-fade-radius", type=float, default=5.0)
    install = parser.add_mutually_exclusive_group()
    install.add_argument(
        "--install-icons",
        action="store_true",
        help="replace the runtime logo and 1024px packaging icon source",
    )
    install.add_argument(
        "--install-splash",
        action="store_true",
        help=f"replace only the splash with a {SPLASH_SIZE}px copy of the input artwork",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.install_splash:
        install_splash(args.input_logo)
        print(RUNTIME_SPLASH)
        return
    output = args.output or args.input_logo.with_name(f"{args.input_logo.stem}_masked.png")
    apply_guide_alpha(
        args.input_logo,
        args.guide,
        output,
        size=args.size,
        opaque_radius=args.opaque_radius,
        feather_radius=args.feather_radius,
        background_alpha_minimum=args.background_alpha_minimum,
        background_alpha_maximum=args.background_alpha_maximum,
        background_opaque_percentile=args.background_opaque_percentile,
        edge_fade_radius=args.edge_fade_radius,
    )
    print(output)
    if args.install_icons:
        install_icon_assets(
            args.input_logo,
            args.guide,
            output,
            size=args.size,
            opaque_radius=args.opaque_radius,
            feather_radius=args.feather_radius,
            background_alpha_minimum=args.background_alpha_minimum,
            background_alpha_maximum=args.background_alpha_maximum,
            background_opaque_percentile=args.background_opaque_percentile,
            edge_fade_radius=args.edge_fade_radius,
        )
        print(RUNTIME_LOGO)
        print(PACKAGING_LOGO_SOURCE)


if __name__ == "__main__":
    main()
