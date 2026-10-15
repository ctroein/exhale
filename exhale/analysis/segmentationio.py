"""HDF5 persistence for derived segmentation results."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import h5py
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ..xrf_refcopy.xrf_sample_class import XRFSample

SEGMENTATION_DIRECTORY = "segmentation"
SEGMENTATION_FORMAT = "exhale-segmentation"
SEGMENTATION_VERSION = 1


def result_relative_path(sample_id: str) -> Path:
    """Return the project-relative sidecar path for one sample."""
    return Path(SEGMENTATION_DIRECTORY) / f"{sample_id}.h5"


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


def save_xrf_sample(sample: XRFSample, filename: str | Path) -> None:
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
            handle.attrs["name"] = sample.name
            handle.attrs["processed"] = sample.is_processed
            handle.attrs["combined"] = sample.is_combined

            nuclei = handle.create_group("nuclei")
            _write_optional_array(nuclei, "raw", sample.nuclei.raw)
            _write_optional_array(nuclei, "nuclei_labels", sample.nuclei.nuclei_labels)
            _write_optional_array(nuclei, "expanded_labels", sample.nuclei.expanded_labels)
            _write_optional_array(nuclei, "membrane_labels", sample.nuclei.membrane_labels)

            tissue = handle.create_group("tissue")
            _write_optional_array(tissue, "raw", sample.tissue.raw)
            _write_optional_array(tissue, "log_image", sample.tissue.log_image)
            _write_optional_array(tissue, "tissue_mask", sample.tissue.tissue_mask)
            _write_optional_array(tissue, "tissue_labels", sample.tissue.tissue_labels)

            elements = handle.create_group("elements")
            for index, channel in enumerate(sample.elements.values()):
                element = elements.create_group(str(index))
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


def load_xrf_sample(filename: str | Path) -> XRFSample:
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

        sample = XRFSample(str(handle.attrs["name"]))
        nuclei_group = handle["nuclei"]
        sample.nuclei = NucleiChannel(nuclei_group["raw"][()])
        sample.nuclei.nuclei_labels = _read_optional_array(nuclei_group, "nuclei_labels")
        sample.nuclei.expanded_labels = _read_optional_array(nuclei_group, "expanded_labels")
        sample.nuclei.membrane_labels = _read_optional_array(nuclei_group, "membrane_labels")
        sample.nuclei._processed = bool(handle.attrs["processed"])

        tissue_group = handle["tissue"]
        sample.tissue = TissueChannel(tissue_group["raw"][()])
        sample.tissue.log_image = _read_optional_array(tissue_group, "log_image")
        sample.tissue.tissue_mask = _read_optional_array(tissue_group, "tissue_mask")
        sample.tissue.tissue_labels = _read_optional_array(tissue_group, "tissue_labels")
        sample.tissue._processed = bool(handle.attrs["processed"])

        for key in sorted(handle["elements"], key=int):
            element_group = handle["elements"][key]
            channel = ElementChannel(str(element_group.attrs["name"]), element_group["raw"][()])
            channel.log_image = _read_optional_array(element_group, "log_image")
            channel.cluster_labels = _read_optional_array(element_group, "cluster_labels")
            channel.intensity_thresholds = _read_optional_array(
                element_group, "intensity_thresholds"
            )
            channel.cluster_df = _read_dataframe(element_group, "cluster_df")
            channel._processed = bool(handle.attrs["processed"])
            sample.elements[channel.name] = channel

        tables = handle["tables"]
        sample._df_nuclei = _read_dataframe(tables, "nuclei")
        sample._df_membrane = _read_dataframe(tables, "membrane")
        sample._df_background = _read_dataframe(tables, "background")
        sample.results_df = _read_dataframe(tables, "results")
        sample._processed = bool(handle.attrs["processed"])
        sample._combined = bool(handle.attrs["combined"])
        return sample
