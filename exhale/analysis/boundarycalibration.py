"""Offline outline perturbations, segment-level holdout and parameter comparison."""

from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
from scipy import ndimage as ndi

from .boundaryfitting import BoundaryFitParameters, fit_boundary


@dataclass
class BoundaryCase:
    """One perturbed outline; all variants of a segment share a train/validation split."""

    sample_id: str
    segment_id: int
    variant: str
    split: str
    bounds: tuple[int, int, int, int]
    image: np.ndarray
    target: np.ndarray
    initial: np.ndarray

    @property
    def key(self):
        return f"{self.sample_id}/{self.segment_id}/{self.variant}"


def make_boundary_cases(image, labels, sample_id, *, seed=0, max_segments=40, max_distance=8):
    """Sample complete connected segments and perturb them without using image values.

    Exclude segments under nine pixels, disconnected IDs and image-edge segments.
    Split by segment before making perturbations, retaining at least one segment
    in each group. The return value includes sampled IDs and explicit exclusions.
    """
    image, labels = np.asarray(image), np.asarray(labels)
    if image.ndim != 2 or labels.shape != image.shape:
        raise ValueError("Source intensities and target labels must have matching 2-D shapes")
    if not np.issubdtype(labels.dtype, np.integer) or (labels < 0).any():
        raise ValueError("Targets must be nonnegative integer instance labels")
    if max_segments < 2:
        raise ValueError("At least two segments are needed for train/validation groups")
    rng = np.random.default_rng(seed)
    identities, counts = np.unique(labels, return_counts=True)
    border = set(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    eligible, excluded = [], {"small": 0, "image_edge": 0, "disconnected": 0}
    for identity, count in zip(identities, counts, strict=True):
        if not identity:
            continue
        if count < 9:
            excluded["small"] += 1
        elif identity in border:
            excluded["image_edge"] += 1
        else:
            eligible.append(int(identity))
    rng.shuffle(eligible)
    selected = []
    for identity in eligible:
        if ndi.label(labels == identity, np.ones((3, 3)))[1] != 1:
            excluded["disconnected"] += 1
        else:
            selected.append(identity)
        if len(selected) == max_segments:
            break
    if len(selected) < 2:
        raise ValueError(f"Sample {sample_id!r} needs at least two eligible segments")
    validation_count = max(1, round(len(selected) * 0.3))
    cases, missing_variants = [], []
    for index, identity in enumerate(selected):
        ys, xs = np.nonzero(labels == identity)
        radius = np.sqrt(len(ys) / np.pi)
        distance = float(np.clip(0.15 * radius, 1, 6))
        margin = int(np.ceil(max_distance + 2 * distance + 10))
        y0, x0 = np.maximum(0, (ys.min() - margin, xs.min() - margin))
        y1, x1 = np.minimum(labels.shape, (ys.max() + margin + 1, xs.max() + margin + 1))
        bounds = tuple(map(int, (y0, y1, x0, x1)))
        crop = np.array(image[y0:y1, x0:x1], copy=True)
        target = labels[y0:y1, x0:x1] == identity
        signed = ndi.distance_transform_edt(target) - ndi.distance_transform_edt(~target)
        noise = ndi.gaussian_filter(rng.normal(size=target.shape), max(1, radius / 3))
        noise = (noise - noise.mean()) / max(float(noise.std()), 1e-10)
        shift = max(1, round(distance))
        variants = {
            "expanded": signed >= -distance,
            "contracted": signed > distance,
            "shifted": ndi.shift(target, (shift, -shift), order=0, mode="constant", cval=0),
            "distorted": signed + distance * noise > 0,
        }
        split = "validation" if index < validation_count else "train"
        for variant, initial in variants.items():
            if not initial.any() or np.array_equal(initial, target):
                missing_variants.append({"segment_id": identity, "variant": variant})
                continue
            cases.append(
                BoundaryCase(sample_id, identity, variant, split, bounds, crop, target, initial)
            )
    if {case.split for case in cases} != {"train", "validation"}:
        raise ValueError("Perturbations did not produce both train and validation examples")
    return cases, {
        "seed": int(seed),
        "selected_segments": selected,
        "excluded": excluded,
        "unused_variants": missing_variants,
    }


def boundary_scores(predicted, target):
    """Return IoU and symmetric mean boundary distance in source-image pixels.

    Empty predictions receive zero IoU and a crop-diagonal distance penalty.
    """
    predicted, target = np.asarray(predicted, bool), np.asarray(target, bool)
    if predicted.shape != target.shape or not target.any():
        raise ValueError("Scoring requires matching masks and a nonempty target")
    iou = np.count_nonzero(predicted & target) / np.count_nonzero(predicted | target)
    if not predicted.any():
        distance = float(np.hypot(*target.shape))
    else:
        p = predicted & ~ndi.binary_erosion(predicted)
        t = target & ~ndi.binary_erosion(target)
        distance = float(
            (ndi.distance_transform_edt(~t)[p].mean() + ndi.distance_transform_edt(~p)[t].mean())
            / 2
        )
    return {"iou": float(iou), "boundary_distance_px": distance, "empty": not predicted.any()}


def parameter_grid(*, iterations=40, max_distance=8):
    """A modest initial search, with settings recorded verbatim in the report."""
    for sigma, smoothing, weight in product((0.75, 1.5), (0, 1), (0.5, 1.0, 2.0)):
        yield BoundaryFitParameters("region", iterations, sigma, smoothing, max_distance, weight)
    for sigma, threshold, balloon in product((0.75, 1.5), (0.3, 0.6), (-1, 0, 1)):
        yield BoundaryFitParameters(
            method="edges",
            iterations=iterations,
            sigma=sigma,
            max_distance=max_distance,
            edge_threshold=threshold,
            balloon=balloon,
        )


def calibrate_boundaries(cases, parameters, *, progress=lambda _done, _total: None):
    """Choose each method's parameters using training segments only, then validate."""
    cases, parameters = list(cases), list(parameters)
    training = [case for case in cases if case.split == "train"]
    validation = [case for case in cases if case.split == "validation"]
    if not training or not validation or not parameters:
        raise ValueError("Calibration requires parameters and train/validation examples")
    if {(c.sample_id, c.segment_id) for c in training} & {
        (c.sample_id, c.segment_id) for c in validation
    }:
        raise ValueError("The same segment cannot occur in both groups")
    records, rankings, done = [], {}, 0
    total = len(training) * len(parameters) + len(validation) * len({p.method for p in parameters})
    for index, settings in enumerate(parameters):
        scores = []
        for case in training:
            score = boundary_scores(fit_boundary(case.image, case.initial, settings), case.target)
            records.append({"case": case.key, "split": "train", "parameter": index, **score})
            scores.append(score)
            done += 1
            progress(done, total)
        ranking = (
            -np.mean([s["iou"] for s in scores]),
            np.mean([s["boundary_distance_px"] for s in scores]),
        )
        if settings.method not in rankings or ranking < rankings[settings.method][0]:
            rankings[settings.method] = (ranking, index)
    best = {method: index for method, (_ranking, index) in rankings.items()}
    for index in best.values():
        for case in validation:
            score = boundary_scores(
                fit_boundary(case.image, case.initial, parameters[index]), case.target
            )
            records.append({"case": case.key, "split": "validation", "parameter": index, **score})
            done += 1
            progress(done, total)
    baseline = [
        {"case": case.key, "split": case.split, **boundary_scores(case.initial, case.target)}
        for case in cases
    ]
    return {
        "parameters": [asdict(p) for p in parameters],
        "best": best,
        "scores": records,
        "baseline": baseline,
    }
