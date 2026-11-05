"""Project-wide export of reviewed source maps, instance masks and provenance."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from tifffile import imwrite

from .. import application_name, exhale_version

if TYPE_CHECKING:
    from ..data.projectdata import ProjectData


def reviewed_candidates(project: ProjectData):
    """Select one reviewed revision per sample, independently of the active view."""
    return [
        candidate
        for _sample_id, history in sorted(project.segmentation_histories.items())
        if (candidate := history.reviewed) is not None
    ]


def export_training_data(project: ProjectData, destination: str | Path) -> int:
    """Publish a new paired-TIFF dataset atomically, preserving source values and IDs.

    Unaccepted working edits and post-processing are excluded. Failed exports leave
    no partial dataset, and existing directories are never overwritten. Newly read
    source caches are released after writing; project and input files are untouched.
    """
    candidates = reviewed_candidates(project)
    if not candidates:
        raise ValueError("No masks are marked as reviewed for training")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"The export directory already exists: {destination}")
    records = []
    with TemporaryDirectory(prefix=".exhale-training-", dir=destination.parent) as temporary:
        root = Path(temporary)
        (root / "images").mkdir()
        (root / "masks").mkdir()
        for index, candidate in enumerate(candidates, 1):
            sample = project.samples.get(candidate.sample_id)
            if sample is None:
                raise ValueError(f"The sample for reviewed mask {candidate.name!r} is unavailable")
            channel = next(
                (
                    channel
                    for channel in sample.channels.values()
                    if channel.ref == candidate.result.input_ref
                ),
                None,
            )
            if channel is None or channel.data_source is None:
                raise ValueError(
                    f"The source element map for sample {sample.name!r} is unavailable"
                )
            data = channel.data_source
            was_cached = data.has_cache
            try:
                image = data.array()
                labels = candidate.result.output.labels
                if image.shape != labels.shape:
                    raise ValueError(
                        f"Source shape {image.shape} differs from mask shape {labels.shape}"
                    )
                image_file = f"images/{index:04d}.tif"
                mask_file = f"masks/{index:04d}.tif"
                imwrite(root / image_file, image, photometric="minisblack", compression=None)
                imwrite(root / mask_file, labels, photometric="minisblack", compression=None)
                ref = candidate.result.input_ref
                asset = project.assets.get(ref.source_id)
                records.append(
                    {
                        "sample_id": sample.sample_id,
                        "sample_name": sample.name,
                        "candidate_id": candidate.candidate_id,
                        "revision_id": candidate.revision_id,
                        "reviewed_revision": candidate.reviewed_revision,
                        "mask_name": candidate.name,
                        "created_at": candidate.created_at,
                        "edited": candidate.edited,
                        "parent_id": candidate.parent_id,
                        "image": image_file,
                        "mask": mask_file,
                        "shape": list(image.shape),
                        "image_dtype": str(image.dtype),
                        "mask_dtype": str(labels.dtype),
                        "source_ref": ref.to_json(),
                        "source_path": None if asset is None else asset.path,
                        "channel_key": channel.key,
                        "channel_name": channel.name,
                        "method_id": candidate.result.method_id,
                        "model_id": candidate.result.output.model_id,
                        "model_version": candidate.result.output.model_version,
                        "parameters": asdict(candidate.result.parameters),
                        "runs": [
                            {**asdict(run), "input_ref": run.input_ref.to_json()}
                            for run in candidate.provenance
                        ],
                    }
                )
            except Exception as error:
                raise ValueError(f"Cannot export sample {sample.name!r}: {error}") from error
            finally:
                if not was_cached:
                    data.release_cache()
        manifest = {
            "format": "exhale-training-data",
            "version": 1,
            "application": application_name,
            "application_version": exhale_version,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_values": "raw",
            "background_label": 0,
            "pixel_resolution": list(project.image_defaults.resolution),
            "abundance_units": project.abundance_units,
            "samples": records,
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Every read and write has succeeded before the dataset becomes visible.
        root.rename(destination)
    return len(records)
