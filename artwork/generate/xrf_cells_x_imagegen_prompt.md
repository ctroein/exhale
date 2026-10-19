# XRF artwork generation pipeline

This directory retains the inputs needed to generate further artwork in the
same visual family. The pipeline has one deterministic geometry stage and one
generative image stage. Generated images must not be used as reference inputs
to later ImageGen calls.

## 1. Generate the geometry guide

The deterministic input is `artwork/generate/16-masks.png`. It is a
four-colour indexed PNG containing background, overlapping masks, yellow-only,
and blue-only pixels. The generator decodes it into separate yellow and blue
masks before fitting the guide contours.

Run from the repository root:

```sh
python artwork/generate/generate_xrf_guide.py \
    --length-coefficient 30 \
    --curvature-coefficient 0
```

The script uses a fixed default seed and writes
`artwork/generate/xrf_guide.png`. That image is the authoritative cell
geometry for the generative stage.

## 2. Run the single ImageGen edit

Use ImageGen in edit/style-transfer mode with exactly these two inputs, in this
order:

1. `artwork/generate/xrf_guide.png`: authoritative geometry target.
2. `artwork/generate/xrf_reference.png`: appearance reference only.

The service does not expose a seed, so the same inputs and prompt define a
repeatable procedure but do not produce pixel-identical output.

```text
Use case: style-transfer
Asset type: square artwork source for an XRF image tool
Pipeline stage: This is the single and only generative transformation. Image 1 is a deterministic mask-derived guide. Image 2 is the original XRF appearance reference. Do not use or imitate any previously generated image.
Geometry: Treat Image 1 as authoritative. Preserve every yellow and blue region's position, approximate footprint, shape, count, overlap, and merged/separate connectivity. Do not add, remove, relocate, split, merge, expand, or contract regions. The arrangement must remain recognizable after reduction to 16x16.
Overall appearance: Reproduce Image 2 as a noisy three-channel elemental map, but with restrained noise suitable for small artwork. Avoid the appearance of fluorescence microscopy, cutout objects, or a polished illustration.
Background: medium-dark green, not nearly black and not brighter than the colored signal. Use broad, soft, low-frequency green and greenish-yellow cellular swirls and faint overlapping tissue forms. The extracellular green material must continuously touch, envelop, and flow around cell edges. There must be no dark moat, outline, halo, or empty separation around colored regions. Avoid isolated background dots, repeated rings, salt-and-pepper noise, and dense granularity.
Yellow regions: Fill most of each yellow footprint with uneven muted yellow, gold, and modest orange signal, with a little reddish-orange variation. Only some cells may contain small irregular greenish patches; do not make cells hollow or fill their interiors mostly with background green. Keep a few partial peripheral concentrations without turning every cell into a ring.
Blue regions: Use moderately bright blue with restrained cyan variation for small-scale visibility. Blend edges softly into adjacent green/cyan tissue so blue does not look pasted on or completely separate. Preserve clear blue identity without neon glow.
Granules: Keep large bright granules rare. Place a few irregular local concentrations in a minority of cells only. Most colored regions should use broad mottled intensity variation. The background should have almost no distinct granules.
Channel overlap: where yellow and blue overlap, show local mixed multichannel signal without an opaque layer or hard boundary.
Edges: softly fading and irregular like an imperfect acquisition, while remaining faithful to the guide footprints.
Avoid: dark cell outlines, bright halos, widespread speckle, repeated circular granules, branching fibrous networks, invented bright objects, text, scale bar, border, watermark.
```

## 3. Retain a selected source

Keep the single full-resolution ImageGen result in
`artwork/generate/xrf_imagegen.png` while evaluating it. Copy the accepted
source into `artwork/logos/` as a 1024 by 1024 PNG. The current selected source
is `artwork/logos/xrf_cells_1024.png`.

The current runtime PNG was finished manually in GIMP and is not yet generated
by the ImageGen stage alone. `apply_guide_alpha.py` can produce a candidate
runtime image by resizing a selected source and applying the guide foreground
with an outward feather:

```sh
python artwork/generate/apply_guide_alpha.py \
    artwork/generate/xrf_imagegen.png \
    --opaque-radius 0 \
    --feather-radius 8 \
    --background-alpha-minimum 0.1 \
    --background-alpha-maximum 0.8 \
    --background-opaque-percentile 95 \
    --edge-fade-radius 5 \
    --output artwork/generate/xrf_logo_alpha.png
```

The original guide foreground remains fully opaque and the feather starts
directly outside it. Elsewhere, relative luminance maps linearly to the
configured background-alpha interval. The cell and background alpha channels
are combined by taking their per-pixel maximum, then the outer edge is faded
to transparency. The background reaches its maximum alpha at the configured
luminance percentile, calculated only from pixels beyond the cell feather;
brighter background pixels are clipped to that maximum. Select the final
source and radii before replacing the packaged runtime logo.

The default command only writes the candidate so it can be inspected. After
inspection, repeat it with `--install` to replace
`exhale/resources/icons/xrf.png`, create the 512 px JPEG splash at
`exhale/resources/xrf_splash.jpg`, and create the 1024 px alpha-processed icon
source at `artwork/logos/xrf_cells_1024.png`. The installation step does not
rebuild the platform icon containers.

## 4. Build platform icons

The Windows and macOS icon containers are derived from the selected source:

```sh
python packaging/build_icons.py \
    artwork/logos/xrf_cells_1024.png \
    --output-base packaging/icons/xrf
```

This requires Pillow and `icnsutil`. It writes `packaging/icons/xrf.ico`
and `packaging/icons/xrf.icns`.
