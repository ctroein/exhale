# XRF artwork generation pipeline

This directory retains the inputs needed to generate further artwork in the
same visual family. The pipeline has deterministic mask and geometry stages,
followed by one ImageGen style-transfer stage. Generated images must not be
used as appearance references in later ImageGen calls.

The 16-pixel branch produces the application, file, and window icons. The
57-pixel branch produces the splash artwork. Variant-specific intermediate
files use `_16` and `_57` suffixes so both branches can remain in this
directory.

## 1. Prepare the indexed masks

`16-masks.png` is the complete indexed input for the icon branch. Its palette
indices represent background, overlap, yellow-only, and blue-only pixels.

`57-mask-y.png` contains the designed yellow geometry for the splash branch:
cells spell “Exhale”, and its initial X also starts the smaller vertical “XRF”.
Add 100 distinct blue points and 40 isolated yellow points with:

```sh
python artwork/generate/sprinkle_mask_points.py \
    --blue-count 100 \
    --yellow-count 40 \
    --seed 5700
```

This writes `57-masks.png`. Each selected pixel has only its blue bit set, so
yellow pixels become overlap pixels rather than losing their yellow channel.
The added yellow pixels have no yellow pixel in their eight-pixel
neighbourhood, including other added pixels. Change `--seed` to obtain another
deterministic sprinkling.

## 2. Generate variant-specific geometry guides

Generate the icon guide with:

```sh
python artwork/generate/generate_xrf_guide.py \
    artwork/generate/16-masks.png \
    --length-coefficient 30 \
    --curvature-coefficient 0
```

This writes `artwork/generate/xrf_guide_16.png` by default.

Generate the splash guide with:

```sh
python artwork/generate/generate_xrf_guide.py \
    artwork/generate/57-masks.png \
    --size 1254 \
    --annealing-steps 300 \
    --seed 1618 \
    --maximum-missed 0.12 \
    --length-coefficient 0.5 \
    --curvature-coefficient 0 \
    --maximum-control-points 80
```

This writes `artwork/generate/xrf_guide_57.png`. The seed controls contour
fitting and background texture; changing it regenerates both deterministically.
The contour tracer retains its exact grid-edge path for simple components,
falls back to bounded marching-squares extraction at edge junctions, and
rasterizes interior letter contours as holes. Annealing evaluates each
component in a padded local crop at the final guide scale, so isolated mask
pixels retain the same area accuracy as the larger letter components.

## 3. Run one ImageGen edit per selected branch

Use ImageGen in edit/style-transfer mode with exactly two inputs, in this
order:

1. The branch's `xrf_guide_*.png`, as the authoritative geometry target.
2. `xrf_reference.png`, as the appearance reference only.

The service does not expose a seed, so the same inputs and prompt define a
repeatable procedure but do not produce pixel-identical output.

Use this shared prompt body:

```text
Use case: style-transfer
Asset type: square artwork source for an XRF image tool
Pipeline stage: This is the single and only generative transformation. Image 1 is a deterministic mask-derived guide. Image 2 is the original XRF appearance reference. Do not use or imitate any previously generated image.
Geometry: Treat Image 1 as authoritative. Preserve every yellow and blue region's position, approximate footprint, shape, count, overlap, and merged/separate connectivity. Do not add, remove, relocate, split, merge, expand, or contract regions.
Overall appearance: Reproduce Image 2 as a noisy three-channel elemental map, but with restrained noise. Avoid the appearance of fluorescence microscopy, cutout objects, or a polished illustration.
Background: medium-dark green, not nearly black and not brighter than the colored signal. Use broad, soft, low-frequency green and greenish-yellow cellular swirls and faint overlapping tissue forms. The extracellular green material must continuously touch, envelop, and flow around cell edges. There must be no dark moat, outline, halo, or empty separation around colored regions. Avoid isolated background dots, repeated rings, salt-and-pepper noise, and dense granularity.
Yellow regions: Fill most of each yellow footprint with uneven muted yellow, gold, and modest orange signal, with a little reddish-orange variation. Only some cells may contain small irregular greenish patches; do not make cells hollow or fill their interiors mostly with background green. Keep a few partial peripheral concentrations without turning every cell into a ring.
Blue regions: Use moderately bright blue with restrained cyan variation for small-scale visibility. Blend edges softly into adjacent green/cyan tissue so blue does not look pasted on or completely separate. Preserve clear blue identity without neon glow.
Granules: Keep large bright granules rare. Place a few irregular local concentrations in a minority of cells only. Most colored regions should use broad mottled intensity variation. The background should have almost no distinct granules.
Channel overlap: where yellow and blue overlap, show local mixed multichannel signal without an opaque layer or hard boundary.
Edges: softly fading and irregular like an imperfect acquisition, while remaining faithful to the guide footprints.
Avoid: dark cell outlines, bright halos, widespread speckle, repeated circular granules, branching fibrous networks, invented bright objects, scale bar, border, watermark.
```

For the 16-pixel icon branch, add:

```text
Small-size constraint: The arrangement must remain recognizable after reduction to 16×16. Do not add text.
```

Keep the selected full-resolution result as `xrf_imagegen_16.png`.

For the 57-pixel splash branch, add:

```text
Letter geometry: The yellow cell regions deliberately spell “Exhale” horizontally, with the initial capital X also beginning the smaller vertical letters “XRF”. Preserve that geometry and readability; do not typeset or overlay ordinary text. Preserve all scattered blue regions. The result must be 1254×1254 pixels.
```

Keep the selected result as `xrf_imagegen_57.png`.

## 4. Install inspected artwork

The runtime icon needs a feathered alpha channel. Generate its inspection
candidate with:

```sh
python artwork/generate/apply_guide_alpha.py \
    artwork/generate/xrf_imagegen_16.png \
    --guide artwork/generate/xrf_guide_16.png \
    --opaque-radius 0 \
    --feather-radius 8 \
    --background-alpha-minimum 0.1 \
    --background-alpha-maximum 0.8 \
    --background-opaque-percentile 95 \
    --edge-fade-radius 5 \
    --output artwork/generate/xrf_logo_alpha_16.png
```

The original guide foreground remains fully opaque and the feather starts
directly outside it. Elsewhere, relative luminance maps linearly to the
configured background-alpha interval. After inspection, repeat the command
with `--install-icons` to replace `exhale/resources/icons/xrf.png` and create
the 1024-pixel packaging source at `artwork/logos/xrf_cells_1024.png`. This
does not change the splash or rebuild platform icon containers.

Install an inspected splash independently with:

```sh
python artwork/generate/apply_guide_alpha.py \
    artwork/generate/xrf_imagegen_57.png \
    --install-splash
```

This replaces only `exhale/resources/xrf_splash.jpg`, resizing the generated
source to 627×627. No alpha-mask candidate is generated for this command.

## 5. Build platform icons

The Windows and macOS icon containers are derived only from the selected icon
source:

```sh
python packaging/build_icons.py \
    artwork/logos/xrf_cells_1024.png \
    --output-base packaging/icons/xrf
```

This requires Pillow and `icnsutil`. It writes `packaging/icons/xrf.ico` and
`packaging/icons/xrf.icns`.
