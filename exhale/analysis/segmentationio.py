"""HDF5 persistence for independent segmentation and element-clustering results."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import h5py
import numpy as np
import pandas as pd

from ..data.segmentation import SegmentationOutput
from ..data.segmentationhistory import SegmentationCandidate, SegmentationHistory

if TYPE_CHECKING:
    from ..data.projectdata import ProjectData, SegmentationResult
    from ..xrf_refcopy.xrf_sample_class import XRFSample

SEGMENTATION_DIRECTORY = "segmentation"
SEGMENTATION_FORMAT = "exhale-segmentation"
SEGMENTATION_VERSION = 1


def result_relative_path(sample_id: str, method_id: str = "stardist") -> Path:
    """Return the project-relative sidecar path for one sample and method."""
    return Path(SEGMENTATION_DIRECTORY) / method_id / f"{sample_id}.h5"


def candidate_relative_path(sample_id: str, candidate_id: str, revision_id: str) -> Path:
    """Use immutable snapshot identities, independent of method or display name."""
    for value in (sample_id, candidate_id, revision_id):
        if not value or Path(value).name != value or value in (".", ".."):
            raise ValueError("Invalid segmentation snapshot path identity")
    return (
        Path(SEGMENTATION_DIRECTORY) / "candidates" / sample_id / candidate_id / f"{revision_id}.h5"
    )


def save_candidate(candidate: SegmentationCandidate, project_dir: str | Path) -> Path:
    """Write a snapshot once; never replace a retained or saved mask."""
    path = Path(project_dir) / candidate_relative_path(
        candidate.sample_id, candidate.candidate_id, candidate.revision_id
    )
    if path.exists():
        with h5py.File(path, "r") as handle:
            if (
                handle.attrs.get("candidate_id") != candidate.candidate_id
                or handle.attrs.get("revision_id") != candidate.revision_id
                or handle.attrs.get("labels_digest") != candidate.labels_digest
            ):
                raise ValueError("An unrelated file occupies the segmentation snapshot path")
        return path
    result = candidate.result
    with _atomic_hdf5(path) as handle:
        handle.attrs.update(
            format=SEGMENTATION_FORMAT,
            version=SEGMENTATION_VERSION,
            candidate_id=candidate.candidate_id,
            revision_id=candidate.revision_id,
            labels_digest=candidate.labels_digest,
            method_id=result.method_id,
            model_id=result.output.model_id,
            model_version=result.output.model_version,
        )
        handle.create_dataset("labels", data=result.output.labels, compression="gzip")
    return path


def publish_segmentation(
    project_data: ProjectData, result: SegmentationResult, project_dir: str | Path
) -> SegmentationCandidate:
    """Save before publication, leaving history untouched when storage fails."""
    if result.sample_id not in project_data.samples:
        raise KeyError(result.sample_id)
    history = project_data.segmentation_histories.get(result.sample_id)
    if history is None:
        history = SegmentationHistory(result.sample_id)
    candidate = SegmentationCandidate.from_result(result)
    save_candidate(history.equivalent(candidate) or candidate, project_dir)
    candidate = history.add_candidate(candidate)
    project_data.segmentation_histories[result.sample_id] = history
    project_data.segmentation_previews.get(result.sample_id, {}).pop(result.method_id, None)
    return candidate


def clustering_relative_path(sample_id: str) -> Path:
    """Return the independent element-clustering sidecar location."""
    return Path("element-clusters") / f"{sample_id}.h5"


def _write_optional_array(group, name, value) -> None:
    if value is not None:
        group.create_dataset(name, data=value, compression="gzip")


def _read_optional_array(group, name):
    return group[name][()] if name in group else None


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, tuple):
        return list(value)
    return value


def _write_dataframe(group, name, dataframe) -> None:
    if dataframe is None:
        return
    payload = {
        "columns": list(dataframe.columns),
        "records": [
            {key: _json_value(value) for key, value in record.items()}
            for record in dataframe.to_dict(orient="records")
        ],
    }
    group.create_dataset(name, data=json.dumps(payload), dtype=h5py.string_dtype("utf-8"))


def _read_dataframe(group, name):
    if name not in group:
        return None
    value = group[name][()]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    payload = json.loads(value)
    return pd.DataFrame(payload["records"], columns=payload["columns"])


@contextmanager
def _atomic_hdf5(filename: str | Path):
    """Replace a completed sidecar atomically, preserving the previous file on error."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=filename.parent, prefix=f".{filename.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
        with h5py.File(temporary, "w") as handle:
            yield handle
            handle.flush()
        os.replace(temporary, filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_segmentation(output: SegmentationOutput, filename: str | Path, *, method_id: str):
    """Save only instance labels and model provenance, without raw maps or XRF state."""
    with _atomic_hdf5(filename) as handle:
        handle.attrs["format"] = SEGMENTATION_FORMAT
        handle.attrs["version"] = SEGMENTATION_VERSION
        handle.attrs["method_id"] = method_id
        handle.attrs["model_id"] = output.model_id
        handle.attrs["model_version"] = output.model_version
        handle.create_dataset("labels", data=output.labels, compression="gzip")


def load_segmentation(
    filename: str | Path, *, expected_method_id: str, candidate_id=None, revision_id=None
) -> SegmentationOutput:
    """Read labels directly, including structurally usable existing sidecars."""
    with h5py.File(filename, "r") as handle:
        if candidate_id is not None and (
            handle.attrs.get("candidate_id") != candidate_id
            or handle.attrs.get("revision_id") != revision_id
        ):
            raise ValueError("Segmentation snapshot identity does not match the project")
        if handle.attrs.get("format") != SEGMENTATION_FORMAT:
            raise ValueError("Not an Exhale segmentation result")
        if int(handle.attrs.get("version", 0)) > SEGMENTATION_VERSION:
            raise ValueError("Unsupported newer segmentation result version")
        stored_method = handle.attrs.get("method_id", expected_method_id)
        if stored_method != expected_method_id:
            raise ValueError("Segmentation result belongs to another method")
        key = "labels" if "labels" in handle else "nuclei/nuclei_labels"
        if key not in handle:
            raise ValueError("Segmentation result has no instance labels")
        output = SegmentationOutput(
            handle[key][()],
            str(handle.attrs.get("model_id", "unknown")),
            str(handle.attrs.get("model_version", "unknown")),
        )
        if candidate_id is not None:
            digest = hashlib.sha256(np.asarray(output.labels.shape, dtype="<u8").tobytes())
            digest.update(np.asarray(output.labels, dtype="<u4").tobytes())
            if handle.attrs.get("labels_digest") != digest.hexdigest():
                raise ValueError("Segmentation snapshot contents do not match their saved identity")
        return output


def save_xrf_sample(
    sample: XRFSample, filename: str | Path, *, method_id: str = "stardist"
) -> None:
    """Atomically store an analyzed sample in an HDF5 sidecar."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=filename.parent,
            prefix=f".{filename.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        with h5py.File(temporary, "w") as handle:
            handle.attrs["format"] = SEGMENTATION_FORMAT
            handle.attrs["version"] = SEGMENTATION_VERSION
            handle.attrs["method_id"] = method_id
            handle.attrs["name"] = sample.name
            handle.attrs["processed"] = sample.is_processed
            handle.attrs["combined"] = sample.is_combined

            if sample.nuclei is not None:
                nuclei = handle.create_group("nuclei")
                nuclei.attrs["processed"] = sample.nuclei.is_processed
                _write_optional_array(nuclei, "raw", sample.nuclei.raw)
                _write_optional_array(nuclei, "nuclei_labels", sample.nuclei.nuclei_labels)
                _write_optional_array(nuclei, "expanded_labels", sample.nuclei.expanded_labels)
                _write_optional_array(nuclei, "membrane_labels", sample.nuclei.membrane_labels)

            if sample.tissue is not None:
                tissue = handle.create_group("tissue")
                tissue.attrs["processed"] = sample.tissue.is_processed
                _write_optional_array(tissue, "raw", sample.tissue.raw)
                _write_optional_array(tissue, "log_image", sample.tissue.log_image)
                _write_optional_array(tissue, "tissue_mask", sample.tissue.tissue_mask)
                _write_optional_array(tissue, "tissue_labels", sample.tissue.tissue_labels)

            elements = handle.create_group("elements")
            for index, channel in enumerate(sample.elements.values()):
                element = elements.create_group(str(index))
                element.attrs["processed"] = channel.is_processed
                element.attrs["name"] = channel.name
                _write_optional_array(element, "raw", channel.raw)
                _write_optional_array(element, "log_image", channel.log_image)
                _write_optional_array(element, "cluster_labels", channel.cluster_labels)
                _write_optional_array(element, "intensity_thresholds", channel.intensity_thresholds)
                _write_dataframe(element, "cluster_df", channel.cluster_df)

            tables = handle.create_group("tables")
            _write_dataframe(tables, "nuclei", sample._df_nuclei)
            _write_dataframe(tables, "membrane", sample._df_membrane)
            _write_dataframe(tables, "background", sample._df_background)
            _write_dataframe(tables, "results", sample.results_df)
            handle.flush()
        os.replace(temporary, filename)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def load_xrf_sample(filename: str | Path, *, expected_method_id: str | None = None) -> XRFSample:
    """Restore an analyzed sample from an HDF5 sidecar."""
    from ..xrf_refcopy.xrf_element_channel import ElementChannel
    from ..xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
    from ..xrf_refcopy.xrf_sample_class import XRFSample

    with h5py.File(filename, "r") as handle:
        if handle.attrs.get("format") != SEGMENTATION_FORMAT:
            raise ValueError("Not an Exhale segmentation result")
        version = int(handle.attrs.get("version", 0))
        if version != SEGMENTATION_VERSION:
            raise ValueError(f"Unsupported segmentation result version {version}")
        stored_method_id = handle.attrs.get("method_id")
        if isinstance(stored_method_id, bytes):
            stored_method_id = stored_method_id.decode("utf-8")
        if (
            expected_method_id is not None
            and stored_method_id is not None
            and stored_method_id != expected_method_id
        ):
            raise ValueError(
                f"Segmentation result belongs to method {stored_method_id!r}, "
                f"not {expected_method_id!r}"
            )

        sample = XRFSample(str(handle.attrs["name"]))
        if "nuclei" in handle:
            nuclei_group = handle["nuclei"]
            sample.nuclei = NucleiChannel(nuclei_group["raw"][()])
            sample.nuclei.nuclei_labels = _read_optional_array(nuclei_group, "nuclei_labels")
            sample.nuclei.expanded_labels = _read_optional_array(nuclei_group, "expanded_labels")
            sample.nuclei.membrane_labels = _read_optional_array(nuclei_group, "membrane_labels")
            sample.nuclei._processed = bool(
                nuclei_group.attrs.get("processed", handle.attrs["processed"])
            )

        if "tissue" in handle:
            tissue_group = handle["tissue"]
            sample.tissue = TissueChannel(tissue_group["raw"][()])
            sample.tissue.log_image = _read_optional_array(tissue_group, "log_image")
            sample.tissue.tissue_mask = _read_optional_array(tissue_group, "tissue_mask")
            sample.tissue.tissue_labels = _read_optional_array(tissue_group, "tissue_labels")
            sample.tissue._processed = bool(
                tissue_group.attrs.get("processed", handle.attrs["processed"])
            )

        for key in sorted(handle["elements"], key=int):
            element_group = handle["elements"][key]
            channel = ElementChannel(str(element_group.attrs["name"]), element_group["raw"][()])
            channel.log_image = _read_optional_array(element_group, "log_image")
            channel.cluster_labels = _read_optional_array(element_group, "cluster_labels")
            channel.intensity_thresholds = _read_optional_array(
                element_group, "intensity_thresholds"
            )
            channel.cluster_df = _read_dataframe(element_group, "cluster_df")
            channel._processed = bool(
                element_group.attrs.get("processed", handle.attrs["processed"])
            )
            sample.elements[channel.name] = channel

        tables = handle["tables"]
        sample._df_nuclei = _read_dataframe(tables, "nuclei")
        sample._df_membrane = _read_dataframe(tables, "membrane")
        sample._df_background = _read_dataframe(tables, "background")
        sample.results_df = _read_dataframe(tables, "results")
        sample._processed = bool(handle.attrs["processed"])
        sample._combined = bool(handle.attrs["combined"])
        return sample
