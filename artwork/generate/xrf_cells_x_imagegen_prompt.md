# XRF artwork generation pipeline

This directory retains the inputs needed to generate further artwork in the
same visual family. The pipeline has deterministic mask and geometry stages,
followed by one ImageGen style-transfer stage. Generated images must not be
used as appearance references in later ImageGen calls.

The 57-pixel mask produces the splash artwork. The application and platform
icons are extracted from its capital X after ImageGen.

## 1. Prepare the indexed masks

`57-mask-y.png` contains the designed yellow geometry for the splash branch:
cells spell “Exhale”, and its initial X also starts the smaller vertical “XRF”.
The indexed mask uses an eight-colour palette whose index bits represent red,
green, and blue respectively from least to most significant bit. Thus yellow
is index 3, blue is index 4, and three-channel overlap is index 7.
Add 95 blue and 10 magenta random-walk spots of up to six pixels each with:

```sh
python artwork/generate/sprinkle_mask_points.py \
    --blue-spot-count 95 \
    --magenta-spot-count 10 \
    --maximum-length 6 \
    --seed 5703
```

This writes `57-masks.png`. Each spot starts at a randomly selected palette-0
pixel whose eight neighbours are also palette 0, then takes random
four-neighbour steps until it reaches six pixels, encounters a pixel whose bit
for that walk's color is already set, or leaves the image. Blue walks continue
through self-collisions; magenta walks stop there. Other colors are combined by
setting the new bits. Blue spots are placed first, followed by magenta spots
under the same starting-clearance rule. Finally, RG pixels with at least three
four-neighbour RG pixels lose their green bit. No yellow points are generated.
The bottom three mask rows are excluded from starting positions, keeping new
spots out of at least the bottom 33 pixels of the 627-pixel splash. Walks may
enter those rows after starting. Change `--seed` to obtain another deterministic
sprinkling.

## 2. Generate the geometry guide

Generate the splash and icon-source guide with:

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
pixels retain the same area accuracy as the larger letter components. Red,
green, and blue bit masks are fitted independently and then recombined, so all
eight palette states follow from the smoothed channel geometry.

## 3. Run one ImageGen edit per selected branch

Use ImageGen in edit/style-transfer mode with exactly two inputs, in this order:

1. `xrf_guide_57.png`, as the authoritative geometry target.
2. `xrf_reference.png`, as the appearance reference only.

The service does not expose a seed, so the same inputs and prompt define a
repeatable procedure but do not produce pixel-identical output.

Use this shared prompt body:

```text
Use case: style-transfer
Asset type: square artwork source for an XRF image tool
Pipeline stage: This is the single and only generative transformation. Image 1 is a deterministic mask-derived guide. Image 2 is the original XRF appearance reference. Do not use or imitate any previously generated image.
Geometry: Treat Image 1 as authoritative. Preserve every colored region's position, approximate footprint, shape, count, overlap, and merged/separate connectivity. Do not add, remove, relocate, split, merge, expand, or contract regions.
Overall appearance: Reproduce Image 2 as a noisy three-channel elemental map, but with restrained noise. Avoid the appearance of fluorescence microscopy, cutout objects, or a polished illustration.
Background: medium-dark green, not nearly black and not brighter than the colored signal. Fill it with numerous subdued cellular forms and related fine tissue structures, softly interwoven and mildly swirly like the appearance reference. Keep them lower-contrast and less prominent than the guide-defined colored regions, while still making the background recognizably cellular rather than empty or uniformly cloudy.
Colored-region structure: Each colored cell-shaped region represents a nucleus-like object in its entirety. Fill its interior with continuous fine-scale swirly, grainy, frothy, or softly mottled XRF texture. Keep every internal feature small relative to the region and distribute variation across the whole footprint, so the region reads as one coherent textured body.
Yellow regions: Fill most of each yellow footprint with uneven muted yellow, gold, and modest orange signal, with a little reddish-orange variation. Use small irregular greenish variations in a minority of regions and retain broad signal through their interiors. Keep a few partial peripheral concentrations while preserving a coherent filled body.
Moss-green regions: Use these regions as locations and approximate extents for plausible textured nucleus-like bodies. Let moss-green signal vary naturally at fine scale throughout each region instead of preserving it as a flat fill. Keep the approximate footprints and avoid neon glow.
Blue-gray and pink-gray regions: Use these regions as locations and approximate extents for additional textured nucleus-like bodies. Their guide colors distinguish signal groups rather than finished fills. Use subdued blue-gray or dull pink-gray signal with restrained fine-scale variation distributed throughout each region.
Texture scale: Use fine grain, soft froth, and small diffuse concentrations. Let broad intensity variation emerge from these small-scale textures rather than from distinct internal objects. Keep the background quieter and less granular than the colored regions.
Channel overlap: where guide colors represent overlapping channels, use both channel contours to shape one coherent cell and show local mixed multichannel signal without an opaque layer or hard boundary.
Edges: clearly localized and moderately crisp while retaining slight natural irregularity and a short soft transition like an imperfect acquisition. Keep the colored regions faithful to the guide footprints without broad diffuse halos.
Avoid: dark cell outlines, bright halos, widespread speckle, repeated circular granules, organelle-like bodies inside the colored regions, branching fibrous networks, invented bright objects, scale bar, border, watermark.
```

Add:

```text
Letter geometry: The yellow cell regions deliberately spell “Exhale” horizontally, with the initial capital X also beginning the smaller vertical letters “XRF”. Preserve that geometry and readability; do not typeset or overlay ordinary text. Preserve all scattered blue and magenta regions. The result must be 1254×1254 pixels.
```

Keep the selected result as `xrf_imagegen_57.png`.

## 4. Install the inspected splash

Install the selected splash with:

```sh
python artwork/generate/install_xrf_splash.py \
    artwork/generate/xrf_imagegen_57.png
```

This writes `exhale/resources/xrf_splash.jpg` at 627×627. The complete generated
artwork remains the splash and retained source rather than a small UI logo. The
installer limits the bottom 28-pixel strip to 25% HSB brightness and blends
that adjustment smoothly through an eight-pixel transition above it.

## 5. Build platform icons

Extract the capital X from the selected splash artwork using the clean X region
in the 57-pixel mask to identify its fitted guide components:

```sh
python artwork/generate/extract_xrf_icon.py
```

This gives the fitted mask a 12-pixel image margin and a four-pixel transition
to dark green, then takes a 360×360 square crop. It writes a desaturated
selection diagnostic, a transparent X with a hard, round-cornered cutout, and
an opaque dark-green version. Add
`--install-runtime` to install a 512-pixel transparent application and Linux
icon, which is also shown in the About dialog. Build the Windows icon from the
transparent source and the macOS icon from the dark source with:

```sh
python packaging/build_icons.py \
    artwork/generate/xrf_icon_x_transparent.png \
    --icns-input artwork/generate/xrf_icon_x_dark.png \
    --output-base packaging/icons/xrf
```

This requires Pillow and `icnsutil`. It writes `packaging/icons/xrf.ico` and
`packaging/icons/xrf.icns`.
