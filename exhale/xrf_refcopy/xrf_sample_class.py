import os
import numpy as np
import pandas as pd
from skimage import io, measure

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
                cluster_n_init: int = 50) -> "XRFSample":
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

        Returns
        -------
        self
        """
        if self.nuclei is None or self.tissue is None:
            raise RuntimeError(
                f"Sample '{self.name}' is missing nuclei ('{self._nuclei_key}') or tissue ('{self._tissue_key}') channel."
            )
        if not self.elements:
            raise RuntimeError(
                f"Sample '{self.name}' has no element channels to process."
            )

        if self._is_nuclei==True:
            self.nuclei.process(
                expansion_px=nuclei_expansion_px,
                min_area=nuclei_min_area
            )
        if self._is_tissue==True:
            self.tissue.process()

        for channel in self.elements.values():
            channel.process(
                min_k=cluster_min_k,
                max_k=cluster_max_k,
                n_init=cluster_n_init
            )

        self._processed = True
        return self

    # ------------------------------------------------------------------
    # Combining results
    # ------------------------------------------------------------------

    def combine(self) -> "XRFSample":
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

        tissue_area, _ = self.tissue.compute_tissue_stats(
            next(iter(self.elements.values())).raw
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
