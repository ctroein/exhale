# XRF cell icon pipeline

This pipeline has one deterministic geometry stage and one generative image
stage. Generated images are never used as inputs to later generation calls.

## 1. Generate the geometry guide

Inputs:

- `icons/16-yellow-mask.png`
- `icons/16-blue-mask.png`

Run from the repository root:

```sh
./packaging/generate_xrf_grid_icon.py \
    --length-coefficient 30 \
    --curvature-coefficient 0 \
    --output packaging/icons/xrf_cells_x_length_30.png
```

The script uses its default fixed seed. The output is the authoritative cell
geometry for the next stage.

## 2. Run one ImageGen edit

Use Codex built-in ImageGen in edit/style-transfer mode with exactly two input
images, in this order:

1. `icons/xrf_cells_x_length_30.png`: authoritative geometry target.
2. The original XRF raster: appearance reference only.

The built-in tool does not expose a seed, so the same inputs and prompt define
a repeatable procedure but do not produce pixel-identical output.

```text
Use case: style-transfer
Asset type: square application icon source for an XRF image tool
Pipeline stage: This is the single and only generative transformation. Image 1 is a deterministic mask-derived guide. Image 2 is the original XRF appearance reference. Do not use or imitate any previously generated image.
Geometry: Treat Image 1 as authoritative. Preserve every yellow and blue region's position, approximate footprint, shape, count, overlap, and merged/separate connectivity. Do not add, remove, relocate, split, merge, expand, or contract regions. The arrangement must remain recognizable after reduction to 16x16.
Overall appearance: Reproduce Image 2 as a noisy three-channel elemental map, but with restrained noise suitable for an icon. Avoid the appearance of fluorescence microscopy, cutout objects, or a polished illustration.
Background: medium-dark green, not nearly black and not brighter than the colored signal. Use broad, soft, low-frequency green and greenish-yellow cellular swirls and faint overlapping tissue forms. The extracellular green material must continuously touch, envelop, and flow around cell edges. There must be no dark moat, outline, halo, or empty separation around colored regions. Avoid isolated background dots, repeated rings, salt-and-pepper noise, and dense granularity.
Yellow regions: Fill most of each yellow footprint with uneven muted yellow, gold, and modest orange signal, with a little reddish-orange variation. Only some cells may contain small irregular greenish patches; do not make cells hollow or fill their interiors mostly with background green. Keep a few partial peripheral concentrations without turning every cell into a ring.
Blue regions: Use moderately bright blue with restrained cyan variation for small-scale visibility. Blend edges softly into adjacent green/cyan tissue so blue does not look pasted on or completely separate. Preserve clear blue identity without neon glow.
Granules: Keep large bright granules rare. Place a few irregular local concentrations in a minority of cells only. Most colored regions should use broad mottled intensity variation. The background should have almost no distinct granules.
Channel overlap: where yellow and blue overlap, show local mixed multichannel signal without an opaque layer or hard boundary.
Edges: softly fading and irregular like an imperfect acquisition, while remaining faithful to the guide footprints.
Avoid: dark cell outlines, bright halos, widespread speckle, repeated circular granules, branching fibrous networks, invented bright objects, text, scale bar, border, watermark.
```

## 3. Save the icon source

Keep the full generated source in the ImageGen output directory. Convert it to
RGB, resize it to 512 by 512 pixels with Pillow's Lanczos filter, and save it
as `icons/xrf_cells_x_length_30_generated.png`. Inspect a separate 16 by 16
Lanczos reduction before selecting the result.
