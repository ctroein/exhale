import os
import numpy as np
import pandas as pd
import time
from skimage import io, measure
from collections.abc import Callable

# from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .xrf_element_channel import ElementChannel
from .xrf_other_channel import NucleiChannel, TissueChannel


class XRFSample:
    """
    Represents a single tissue sample with all its XRF channels.

    Holds one NucleiChannel, one TissueChannel, and any number of
    ElementChannels. Handles loading from files, processing all channels,
    and combining results into per-region dataframes.

    Attributes
    ----------
    name : str
        Sample identifier (e.g. folder name).
    nuclei : NucleiChannel | None
    tissue : TissueChannel | None
    elements : dict[str, ElementChannel]
        Keyed by element name (e.g. 'Ca', 'Cu').
    results_df : pd.DataFrame | None
        Flat per-cluster dataframe after combine(). Contains columns:
        element, cluster_size, cluster_intensity, location, samples, tissue_area.
    _processed : bool
    _combined : bool
    """

    def __init__(self, name: str):
        self.name = name

        self._is_nuclei = True
        self._nuclei_key = 'wP_'
        self.nuclei: NucleiChannel | None = None
        self._df_nuclei: pd.DataFrame | None = None
        self._df_membrane: pd.DataFrame | None = None
        self._df_background: pd.DataFrame | None = None

        self._is_tissue = True
        self._tissue_key = 'wCl_'
        self.tissue: TissueChannel | None = None

        self.elements: dict[str, ElementChannel] = {}
        self.results_df: pd.DataFrame | None = None

        self._processed = False
        self._combined = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def from_folder(cls, folder: str,
                    element_keys: list[str]) -> "XRFSample":
        """
        Instantiate an XRFSample by scanning a folder for image files.

        Parameters
        ----------
        folder : str
            Path to the sample folder.
        element_keys : list[str]
            Filename substrings that identify element channels
            (e.g. ['wCa_', 'wCu_', 'wFe_', 'wZn_']).
            'wP_' and 'wCl_' are handled automatically and should NOT
            be included in this list.

        Returns
        -------
        XRFSample (unprocessed — call .process() to run the pipeline)
        """
        sample_name = os.path.basename(folder.rstrip(os.sep))
        sample = cls(sample_name)

        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue

            img = io.imread(fpath)

            if sample._nuclei_key in fname:
                sample.nuclei = NucleiChannel(img)

            elif sample._tissue_key in fname:
                sample.tissue = TissueChannel(img)

            else:
                for key in element_keys:
                    if key in fname:
                        element_name = key.replace('w', '').replace('_', '')
                        sample.elements[element_name] = ElementChannel(element_name, img)
                        break

        return sample

    def add_element(self, name: str, raw: np.ndarray) -> None:
        """Manually add or replace an element channel."""
        self.elements[name] = ElementChannel(name, raw)

    def remove_element(self, name: str):
        """Manually remove an element channel."""
        del self.elements[name]

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, nuclei_expansion_px: int = 15,
                nuclei_min_area: int = 100,
                cluster_min_k: int = 3,
                cluster_max_k: int = 25,
                cluster_n_init: int = 50,
                callback: Callable[[str], None] = None) -> "XRFSample":
        """
        Process all channels in order: nuclei -> tissue -> elements.

        Parameters
        ----------
        nuclei_expansion_px : int
            Pixel expansion for membrane ring around nuclei.
        nuclei_min_area : int
            Minimum nucleus area to retain.
        cluster_min_k, cluster_max_k : int
            KMeans cluster count search range for element channels.
        cluster_n_init : int
            KMeans initialisations per k.
        callback : Callable[str]
            Progress callback function, optional.

        Returns
        -------
        self
        """
        if self.nuclei is None or self.tissue is None:
            raise RuntimeError(
                f"Sample '{self.name}' is missing nuclei ('{self._nuclei_key}')"
                f" channel or tissue ('{self._tissue_key}') channel."
            )
        # if not self.elements:
        #     raise RuntimeError(
        #         f"Sample '{self.name}' has no element channels to process."
        #     )
        if callback is None:
            callback = lambda x: None

        if self._is_nuclei==True:
            self.nuclei.process(
                expansion_px=nuclei_expansion_px,
                min_area=nuclei_min_area,
                callback=callback
            )
        if self._is_tissue==True:
            callback("Processing tissue")
            self.tissue.process()

        for channel in self.elements.values():
            channel.process(
                min_k=cluster_min_k,
                max_k=cluster_max_k,
                n_init=cluster_n_init,
                callback=callback
            )

        self._processed = True
        return self

    # ------------------------------------------------------------------
    # Combining results
    # ------------------------------------------------------------------

    def combine(self, callback: Callable[[str], None] = None) -> "XRFSample":
        """
        Assign clusters to regions (nuclei / membrane / background) and
        build the flat results dataframe.

        Must be called after process().

        Returns
        -------
        self
        """
        if not self._processed:
            raise RuntimeError("Call process() before combine().")

        df_nuclei, df_membrane, df_background = [], [], []

        for element_name, channel in self.elements.items():
            if callback is not None:
                callback(f"Processing {element_name}")
            temp_df = channel.cluster_df.copy()
            tissue_area, tissue_mean_intensity = self.tissue.compute_tissue_stats(
                channel.raw
            )

            # Assign clusters to nuclei
            temp_df = self._assign_region(
                self.nuclei.nuclei_labels, channel.log_image,
                element_name, temp_df, 'nuclei', df_nuclei
            )
            # Assign remaining clusters to membrane
            temp_df = self._assign_region(
                self.nuclei.membrane_labels, channel.log_image,
                element_name, temp_df, 'membrane', df_membrane
            )
            # Whatever remains is non-cellular background
            self._assign_background(
                element_name, temp_df, tissue_mean_intensity, df_background
            )

        self._df_nuclei = pd.DataFrame(df_nuclei)
        self._df_membrane = pd.DataFrame(df_membrane)
        self._df_background = pd.DataFrame(df_background)

        if callback is not None:
            callback("Computing tissue stats")
        tissue_area, _ = self.tissue.compute_tissue_stats(
            self.tissue.raw
            # next(iter(self.elements.values())).raw
        )

        flat_nuclei = self._flatten(self._df_nuclei, 'nuclei')
        flat_membrane = self._flatten(self._df_membrane, 'membrane')
        flat_background = self._flatten(self._df_background, 'non_cellular')

        self.results_df = pd.concat(
            [flat_nuclei, flat_membrane, flat_background],
            ignore_index=True
        )
        self.results_df['samples'] = self.name
        self.results_df['tissue_area'] = tissue_area

        for df in (self._df_nuclei, self._df_membrane, self._df_background):
            df['samples'] = self.name

        self._combined = True
        return self

    # ------------------------------------------------------------------
    # Region assignment helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_region(region_labels: np.ndarray, element_img: np.ndarray,
                       element_name: str, cluster_df: pd.DataFrame,
                       region_name: str, results: list) -> pd.DataFrame:
        """
        For each labelled region, find clusters whose centroid falls within
        the region bounding box, record stats, then remove those clusters
        from cluster_df so they aren't double-counted.

        Returns the remaining (unassigned) cluster_df.
        """
        for region in measure.regionprops(region_labels, element_img):
            min_row, min_col, max_row, max_col = region.bbox

            in_region = cluster_df[
                (cluster_df['centroid-0'] > min_row) &
                (cluster_df['centroid-0'] < max_row) &
                (cluster_df['centroid-1'] > min_col) &
                (cluster_df['centroid-1'] < max_col)
            ]

            n = in_region.shape[0]
            results.append({
                'label': region.label,
                'element': element_name,
                'region': region_name,
                'num_clusters': n,
                'cluster_sizes': in_region['area'].values if n else [],
                'cluster_intensities': in_region['mean_intensity'].values if n else [],
                'average_element_intensity': region.intensity_mean
            })

            cluster_df = cluster_df.drop(in_region.index)

        return cluster_df

    @staticmethod
    def _assign_background(element_name: str, remaining_df: pd.DataFrame,
                           tissue_mean_intensity: float, results: list) -> None:
        """Record all remaining unassigned clusters as non-cellular background."""
        n = remaining_df.shape[0]
        results.append({
            'label': 1000,  # dummy label for background
            'element': element_name,
            'region': 'non_cellular',
            'num_clusters': n,
            'cluster_sizes': remaining_df['area'].values if n else [],
            'cluster_intensities': remaining_df['mean_intensity'].values if n else [],
            'average_element_intensity': tissue_mean_intensity
        })

    @staticmethod
    def _flatten(df: pd.DataFrame, location: str) -> pd.DataFrame:
        """
        Expand per-region list columns (cluster_sizes, cluster_intensities)
        into one row per cluster.
        """
        rows = []
        for _, row in df.iterrows():
            for size, intensity in zip(row['cluster_sizes'],
                                       row['cluster_intensities']):
                rows.append({
                    'element': row['element'],
                    'cluster_size': size,
                    'cluster_intensity': intensity,
                    'location': location
                })
        return pd.DataFrame(rows)


    # ------------------------------------------------------------------
    # Data export
    # ------------------------------------------------------------------
    def export_results(self, outdir: str | Path, *,
        save_raw: bool = True,
        save_cluster_labels: bool = True,
        save_nuclei_labels: bool = True,
        save_membrane_labels: bool = True,
        save_tissue_labels: bool = True,
        save_tissue_mask: bool = True,
        add_subdir = True,
        csv_sep: str = ",",
    ) -> Path:
        """
        Export analysis outputs for this sample.

        Parameters
        ----------
        outdir:
            Output directory. Created if missing.
        save_raw:
            Also export raw channel images as TIFF.
        save_cluster_labels:
            Export per-element connected-component cluster label images.
        save_nuclei_labels:
            Export filtered nuclei labels.
        save_membrane_labels:
            Export membrane ring labels.
        save_tissue_labels:
            Export connected-component tissue labels.
        save_tissue_mask:
            Export binary tissue mask.
        add_subdir:
            Save in a subdirectory with timestamp in name.
        csv_sep:
            CSV separator.

        Returns
        -------
        Path
            Path to the created sample export directory.
        """
        outdir = Path(outdir)
        if add_subdir:
            outdir = outdir / time.strftime("export_%F_%H%M%S")
        outdir.mkdir(parents=True, exist_ok=True)

        masks_dir = "masks"
        clusters_dir = "clusters"
        tables_dir = "tables"
        channels_dir = "channels"
        for d in (masks_dir, clusters_dir, tables_dir, channels_dir):
            (outdir / d).mkdir(exist_ok=True)

        manifest: dict[str, Any] = {
            "sample": self.name,
            "processed": self._processed,
            "combined": self._combined,
            "elements": self.element_names,
            "files": {},
            "elem_files": {}
        }

        def _save(mf: dict, reldir: str, data: np.ndarray | pd.DataFrame,
                  name: str, elem: str = None) -> None:
            pref = "" if elem is None else elem + "_"
            if isinstance(data, np.ndarray):
                ftype = "tif"
            elif isinstance(data, pd.DataFrame):
                ftype = "csv"
            else:
                raise ValueError("unknown ftype")
            p = os.path.join(reldir, pref + name + "." + ftype)
            if ftype == "tif":
                # Keep integer labels as integer TIFFs, float images as float TIFFs
                io.imsave(str(outdir / p), data, check_contrast=False)
            elif ftype == "csv":
                data.to_csv(str(outdir / p), index=False, sep=csv_sep)
            mf[name] = p

        def _jsonable(v: Any) -> Any:
            if isinstance(v, np.ndarray):
                return v.tolist()
            if isinstance(v, (np.integer, np.floating)):
                return v.item()
            if isinstance(v, Path):
                return str(v)
            return v

        mf = manifest["files"]
        # Global masks / labels
        if self.nuclei is not None:
            if save_raw:
                _save(mf, channels_dir, self.nuclei.raw, "nuclei_raw")
            if save_nuclei_labels and self.nuclei.nuclei_labels is not None:
                _save(mf, masks_dir, self.nuclei.nuclei_labels.astype(np.int32),
                      "nuclei_labels")
            if save_membrane_labels and self.nuclei.membrane_labels is not None:
                _save(mf, masks_dir, self.nuclei.membrane_labels.astype(np.int32),
                      "membrane_labels")
        if self.tissue is not None:
            if save_raw:
                _save(mf, channels_dir, self.tissue.raw, "tissue_raw")
            if save_tissue_mask and self.tissue.tissue_mask is not None:
                _save(mf, masks_dir, self.tissue.tissue_mask.astype(np.uint8),
                      "tissue_mask")
            if save_tissue_labels and self.tissue.tissue_labels is not None:
                _save(mf, masks_dir, self.tissue.tissue_labels.astype(np.int32),
                      "tissue_labels")

        # Per-element exports
        for element_name, ch in self.elements.items():
            emf = manifest["elem_files"].setdefault(element_name, {})
            if save_raw:
                _save(emf, channels_dir, ch.raw, "raw", element_name)
            if save_cluster_labels and ch.cluster_labels is not None:
                _save(emf, clusters_dir, ch.cluster_labels.astype(np.int32),
                      "cluster_labels", element_name)
            if ch.cluster_df is not None:
                _save(emf, tables_dir, ch.cluster_df,
                      "cluster_regions", element_name)

        # Combined result tables
        if self.results_df is not None:
            _save(mf, tables_dir, self.results_df, "results_flat")
        if self._df_nuclei is not None:
            _save(mf, tables_dir, self._prepare_object_df_for_csv(self._df_nuclei),
                  "results_nuclei")
        if self._df_membrane is not None:
            _save(mf, tables_dir, self._prepare_object_df_for_csv(self._df_membrane),
                  "results_membrane")
        if self._df_background is not None:
            _save(mf, tables_dir, self._prepare_object_df_for_csv(self._df_background),
                  "results_background")

        # Metadata manifest
        manifest["status"] = {
            "processed": self._processed,
            "combined": self._combined,
            "n_nuclei_labels": int(np.max(self.nuclei.nuclei_labels))
            if self.nuclei is not None and self.nuclei.nuclei_labels is not None
            else 0,
            "n_membrane_labels": int(np.max(self.nuclei.membrane_labels))
            if self.nuclei is not None and self.nuclei.membrane_labels is not None
            else 0,
            "n_elements": len(self.elements),
        }

        manifest_path = outdir / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=_jsonable)
        return str(outdir)


    @staticmethod
    def _prepare_object_df_for_csv(df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert array/list-valued columns to JSON strings for CSV export.
        """
        out = df.copy()
        for col in out.columns:
            if out[col].dtype == object:
                out[col] = out[col].map(XRFSample._object_to_json_string)
        return out

    @staticmethod
    def _object_to_json_string(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return json.dumps(value.tolist())
        if isinstance(value, list):
            return json.dumps(value)
        if isinstance(value, tuple):
            return json.dumps(list(value))
        return value
    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def is_processed(self) -> bool:
        return self._processed

    @property
    def is_combined(self) -> bool:
        return self._combined

    @property
    def element_names(self) -> list[str]:
        return list(self.elements.keys())

    @property
    def df_nuclei(self) -> pd.DataFrame:
        """
        Per-nucleus, per-element cluster summary. One row per (nucleus label, element).
        Columns: label, element, region, num_clusters, cluster_sizes,
                 cluster_intensities, average_element_intensity, samples.
        Populated after combine().
        """
        if self._df_nuclei is None:
            raise RuntimeError("Call combine() before accessing df_nuclei.")
        return self._df_nuclei

    @property
    def df_membrane(self) -> pd.DataFrame:
        """
        Per-membrane-ring, per-element cluster summary. Same schema as df_nuclei.
        Populated after combine().
        """
        if self._df_membrane is None:
            raise RuntimeError("Call combine() before accessing df_membrane.")
        return self._df_membrane

    @property
    def df_background(self) -> pd.DataFrame:
        """
        Non-cellular background cluster summary. Same schema as df_nuclei.
        Populated after combine().
        """
        if self._df_background is None:
            raise RuntimeError("Call combine() before accessing df_background.")
        return self._df_background

    def get_element(self, name: str) -> ElementChannel:
        if name not in self.elements:
            raise KeyError(f"Element '{name}' not found. Available: {self.element_names}")
        return self.elements[name]

    def set_nuclei_key(self, key: str):
        self._nuclei_key = key

    def set_tissue_key(self, key: str):
        self._tissue_key = key

    def __repr__(self) -> str:
        status = "combined" if self._combined else ("processed" if self._processed else "unprocessed")
        return (f"XRFSample(name='{self.name}', "
                f"elements={self.element_names}, "
                f"status={status})")
