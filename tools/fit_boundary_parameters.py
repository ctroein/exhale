#!/usr/bin/env python3
"""Compare edge/region outline fitting against accepted masks in a saved Exhale project.

Reads source intensities and saved labels without running segmentation, opening
windows or saving the project. Outputs a reproducible report and example crops.
"""

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exhale import exhale_version
from exhale.analysis.boundarycalibration import (
    calibrate_boundaries,
    make_boundary_cases,
    parameter_grid,
)
from exhale.analysis.boundaryfitting import fit_boundary
from exhale.data.projectdata import ProjectData
from exhale.data.segmentation import SegmentationPostprocessing
from exhale.data.source_refs import SourceUnavailableError
from exhale.project.projectio import load_project


def _choose(objects, selector, kind):
    identity = "sample_id" if kind == "sample" else "candidate_id"
    matches = [obj for obj in objects if selector in (getattr(obj, identity), obj.name)]
    if len(matches) != 1:
        raise ValueError(f"{kind.capitalize()} {selector!r} must match exactly one name or ID")
    return matches[0]


def _summary(scores):
    return {
        "mean_iou": float(np.mean([score["iou"] for score in scores])),
        "mean_boundary_distance_px": float(
            np.mean([score["boundary_distance_px"] for score in scores])
        ),
        "empty_fits": sum(score["empty"] for score in scores),
        "cases": len(scores),
    }


def _preview(case, fitted, filename):
    """Draw reference/candidate boundaries over raw-intensity diagnostic crops."""
    data = case.image.astype(float)
    finite = np.isfinite(data)
    low, high = np.percentile(data[finite], (1, 99.9))
    gray = np.zeros(data.shape, np.uint8)
    if high > low:
        gray[finite] = np.clip((data[finite] - low) / (high - low) * 255, 0, 255).astype(np.uint8)
    scale = max(1, min(6, 320 // max(gray.shape)))
    width, height = gray.shape[1] * scale, gray.shape[0] * scale
    panels = [("Initial", case.initial), *fitted.items()]
    canvas = Image.new("RGB", ((width + 12) * len(panels) + 12, height + 54), "#202020")
    painter = ImageDraw.Draw(canvas)
    target_edge = case.target & ~ndi.binary_erosion(case.target)
    for index, (name, mask) in enumerate(panels):
        rgb = np.repeat(gray[:, :, None], 3, axis=2)
        edge = mask & ~ndi.binary_erosion(mask)
        rgb[target_edge] = (0, 255, 80)
        rgb[edge] = (255, 210, 0) if name == "Initial" else (255, 50, 200)
        rgb[edge & target_edge] = (255, 255, 255)
        x = 12 + index * (width + 12)
        canvas.paste(
            Image.fromarray(rgb).resize((width, height), Image.Resampling.NEAREST), (x, 24)
        )
        painter.text((x, 5), name, fill="white")
    painter.text(
        (12, height + 30),
        "Reference green / initial yellow / fit magenta / overlap white",
        fill="white",
    )
    canvas.save(filename)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="project directory or project.xhp")
    parser.add_argument(
        "--list", action="store_true", help="list samples and masks without fitting"
    )
    parser.add_argument(
        "--sample", action="append", help="sample name or ID; repeat to select several"
    )
    parser.add_argument(
        "--mask", help="mask name or ID for one sample; otherwise use its saved active mask"
    )
    parser.add_argument(
        "--output", type=Path, help="new output directory; defaults beneath project/exports"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--max-segments", type=int, default=40, help="maximum per sample (default 40)"
    )
    parser.add_argument(
        "--iterations", type=int, default=40, help="evolution steps per fit (default 40)"
    )
    parser.add_argument(
        "--max-distance", type=float, default=8, help="maximum boundary displacement in pixels"
    )
    parser.add_argument(
        "--previews", type=int, default=12, help="number of validation-case PNG/NPZ pairs"
    )
    args = parser.parse_args(argv)
    filename = args.project / "project.xhp" if args.project.is_dir() else args.project
    model = ProjectData()
    try:
        for issue in load_project(model, filename):
            print(f"Project loading: {issue}", file=sys.stderr)
        if args.list:
            for sample in model.samples.values():
                print(f"Sample: {sample.name} [{sample.sample_id}]")
                history = model.segmentation_histories.get(sample.sample_id)
                for candidate in () if history is None else history.candidates.values():
                    marker = " (active)" if candidate is history.active else ""
                    print(f"  Mask: {candidate.name} [{candidate.candidate_id}]{marker}")
            return
        if args.previews < 0:
            raise ValueError("Preview count cannot be negative")
        samples = list(model.samples.values())
        if args.sample:
            samples = [_choose(samples, selector, "sample") for selector in args.sample]
        samples = list({sample.sample_id: sample for sample in samples}.values())
        if args.mask and len(samples) != 1:
            raise ValueError("--mask requires exactly one selected sample")
        settings = list(parameter_grid(iterations=args.iterations, max_distance=args.max_distance))
        cases, sources = [], []
        for index, sample in enumerate(samples):
            history = model.segmentation_histories.get(sample.sample_id)
            if history is None or history.active is None:
                if args.sample:
                    raise ValueError(f"Sample {sample.name!r} has no saved mask")
                continue
            candidate = (
                _choose(history.candidates.values(), args.mask, "mask")
                if args.mask
                else history.active
            )
            ref = candidate.result.input_ref
            image = model.assets[ref.source_id].source.load_array(ref)
            reference = replace(
                model.segmentation_reference(sample.sample_id, candidate.candidate_id),
                postprocessing=SegmentationPostprocessing(),
            )
            labels = model.resolve_segmentation_reference(reference)
            sample_seed = np.random.SeedSequence([args.seed, index]).generate_state(1)[0]
            current, selection = make_boundary_cases(
                image,
                labels,
                sample.sample_id,
                seed=int(sample_seed),
                max_segments=args.max_segments,
                max_distance=args.max_distance,
            )
            cases.extend(current)
            sources.append(
                {
                    "sample_name": sample.name,
                    "mask_name": candidate.name,
                    "reference": reference.to_json(),
                    "nuclei_ref": asdict(ref),
                    "provenance": [asdict(run) for run in candidate.provenance],
                    "selection": selection,
                }
            )
        if not cases:
            raise ValueError("No selected sample has a saved segmentation mask")
        output = args.output or filename.parent / "exports" / datetime.now().strftime(
            "boundary-fit_%Y%m%d_%H%M%S"
        )
        if output.exists():
            raise ValueError(f"Output directory already exists: {output}")
        last_progress = 0.0

        def progress(done, total):
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress >= 0.5 or done == total:
                print(
                    f"\rFitting {done}/{total}",
                    end="\n" if done == total else "",
                    file=sys.stderr,
                    flush=True,
                )
                last_progress = now

        results = calibrate_boundaries(cases, settings, progress=progress)
        summaries = {}
        for split in ("train", "validation"):
            summaries[split] = {
                "initial": _summary([row for row in results["baseline"] if row["split"] == split])
            }
            for method, best_index in results["best"].items():
                summaries[split][method] = _summary(
                    [
                        row
                        for row in results["scores"]
                        if row["split"] == split and row["parameter"] == best_index
                    ]
                )
        output.mkdir(parents=True)
        previews = []
        validation = [c for c in cases if c.split == "validation"]
        preview_indices = np.linspace(
            0, len(validation) - 1, min(args.previews, len(validation)), dtype=int
        )
        for index, case_index in enumerate(preview_indices):
            case = validation[case_index]
            fitted = {
                method: fit_boundary(case.image, case.initial, settings[best_index])
                for method, best_index in results["best"].items()
            }
            stem = f"example_{index + 1:03d}"
            np.savez_compressed(
                output / f"{stem}.npz",
                image=case.image,
                target=case.target,
                initial=case.initial,
                **fitted,
            )
            _preview(case, fitted, output / f"{stem}.png")
            previews.append({"case": case.key, "files": [f"{stem}.png", f"{stem}.npz"]})
        report = {
            "format": "exhale-boundary-calibration",
            "project": str(filename.resolve()),
            "seed": args.seed,
            "versions": {
                "exhale": exhale_version,
                **{name: version(name) for name in ("numpy", "scipy", "scikit-image")},
            },
            "sources": sources,
            "cases": [
                {
                    "case": c.key,
                    "sample_id": c.sample_id,
                    "segment_id": c.segment_id,
                    "variant": c.variant,
                    "split": c.split,
                    "bounds": c.bounds,
                }
                for c in cases
            ],
            "summaries": summaries,
            "previews": previews,
            **results,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        with (output / "scores.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("case", "split", "parameter", "iou", "boundary_distance_px", "empty"),
            )
            writer.writeheader()
            writer.writerows([{**row, "parameter": "initial"} for row in results["baseline"]])
            writer.writerows(results["scores"])
        print(f"Results: {output}")
    except (OSError, ValueError, KeyError, SourceUnavailableError) as exc:
        parser.exit(1, f"Boundary fitting failed: {exc}\n")
    finally:
        for source in model.sources.values():
            source.close()


if __name__ == "__main__":
    main()
