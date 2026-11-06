# Offline boundary-fitting experiment

This experiment compares two ways of fitting an approximate outline to the
nuclei channel: an edge-based geodesic contour and a region-intensity Chan–Vese
contour. It reads a saved project without running neural segmentation or changing
the project. These are the earlier pixel-mask methods; the editor now uses the
contour-normal heuristic described below, with only its displacement limit exposed.
The command-line experiment retains the earlier methods for comparison.

## Preparing and choosing masks

Save the project after running segmentation or accepting corrections. Experiments
use accepted masks before expansion/shrinking and minimum-area filtering, together
with the original nuclei-channel intensities. Unaccepted editing drafts and
viewer gain/color adjustments are not inputs.

List the available samples and masks from the repository root:

```bash
python tools/fit_boundary_parameters.py /path/to/project --list
```

Fit using one sample's saved active mask:

```bash
python tools/fit_boundary_parameters.py /path/to/project --sample "Sample name"
```

To use a particular mask, add `--mask "Mask name"`. Names must be unambiguous;
IDs from the listing also work. Repeat `--sample` for several samples, using each
sample's saved active mask. Omitting `--sample` uses every sample with a saved
mask. `--mask` is restricted to one selected sample.

Results go into a new directory beneath the project's `exports` directory, or
into the new directory given by `--output`. Existing output directories are
never overwritten. No project or segmentation files are saved by this tool.

## What is compared

At most 40 segments per sample are randomly sampled, using seed 0 by default.
Segments under nine pixels, segments touching the image edge, and disconnected
segment IDs are excluded. The report records selected IDs and exclusions encountered while sampling.

Approximately 30% of sampled segments are held out for validation. All versions
of a segment stay in the same group. Starting outlines are expanded, contracted,
shifted and smoothly distorted. Perturbation size is 15% of equivalent radius,
bounded to 1–6 pixels; empty or unchanged perturbations are skipped and recorded.
This tests recovery from approximate outlines rather than merely preservation of
an already correct boundary.

Each fit uses a local image crop, rescaled between its 1st and 99.9th intensity
percentiles. Non-finite intensities are replaced by the local finite median.
The evolving contour cannot move more than eight pixels from the initial
boundary. This limit can be changed with `--max-distance`. Defaults are 40
iterations per fit and 24 parameter combinations in total. `--iterations`,
`--max-segments` and `--seed` can reduce workload or vary the experiment.

The region search varies image smoothing, contour smoothing and the relative
inside/outside intensity weight. The edge search varies image smoothing, edge
threshold and inflation/contraction direction. The entire parameter grid is
recorded in the report. Curvature smoothing has per-fit state so earlier trials
do not change later results.

Parameters are chosen separately for each method using mean training overlap
(intersection over union, IoU). Mean boundary distance breaks ties. The selected
parameters are then evaluated on the withheld segments. Boundary distance is the
mean of the two directional mean distances, in source-image pixels. Empty fits
receive zero overlap and a crop-diagonal boundary-distance penalty.

The unfitted outlines are scored as a baseline. A fitted result need not improve
on that baseline. Existing segmentation is a provisional target, not ground
truth: agreement can reproduce segmentation mistakes. Withheld segments from the
same experiment do not establish performance on other tissues or instruments.

## Outputs

`report.json` contains source identities, model/run provenance, seeds, selected
segments, train/validation assignments, crop bounds, all parameter combinations,
the chosen settings, baseline and fitted scores, and library versions.
`scores.csv` contains individual scores for easier inspection.

By default, up to twelve validation examples are written as PNG/NPZ pairs.
The PNG compares the initial outline and each fitted result over the nuclei
image. Reference boundaries are green, the initial outline yellow, fitted
boundaries magenta, and coincident boundary pixels white. NPZ files contain the
original intensity crop and the target, initial and fitted binary masks.
Use `--previews` to change the number. Images are written to disk and are not
opened automatically.

## Current drawing-tool heuristic

`fit_outline` resamples each boundary at approximately one-pixel arc-length
intervals and smooths its tangent over 1.5 samples to obtain local normals. It
searches inward/outward along those normals within the requested adjustment
range. Up to 65 distinct offsets combine 33 uniform samples across that range
with 33 samples within eight pixels, retaining fine sampling for large ranges.

The source map is rescaled between local 1st/99.9th percentiles. Gaussian
image derivatives use sigma 1.5 pixels. Only outward intensity decreases earn
an edge reward, weighted by squared directional alignment. Reward saturates at
the 90th percentile of positive normal-gradient values for the current loop,
so a few very strong edges cannot dominate the score without limit.

The pointwise cost is negative edge reward plus 0.6 times squared displacement
relative to the adjustment range. A cyclic dynamic program adds 0.2 times squared
neighboring displacement differences, including the closing edge. A final cyclic
least-squares smoothing step penalizes second differences with weight 2. This
smooths the adjustment rather than shortening the original boundary.

The rasterized mask must remain within the hard displacement bounds and exclude
protected pixels. If component or hole counts change, retry at one-half,
one-quarter and one-eighth displacement, otherwise retain the drawing. This is
a conservative heuristic; preserving topology does not prove that a selected
edge is biologically correct.

The engineering comparison used five eligible segments from each of 11 exported
samples (seed 47), with outlines expanded by two/six pixels and shifted by four
pixels in both axes. The references were unedited Cellpose masks. This tests
outline recovery, not agreement with independent manual annotations. Synthetic
regressions additionally cover extreme internal bright spots, edge polarity,
cyclic seam independence, protected pixels, holes and displacement bounds.
