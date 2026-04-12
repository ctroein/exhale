import numpy as np
import pandas as pd
from skimage import measure
from collections.abc import Callable

from . import xrf_utils as xu


class NucleiChannel:
    """
    Represents the phosphorus (P) channel used for nuclear segmentation.

    Attributes
    ----------
    raw : np.ndarray
        Raw intensity image.
    nuclei_labels : np.ndarray
        Filtered, segmented nuclei label image. Populated after process().
    expanded_labels : np.ndarray
        Nuclei labels expanded outward by `expansion_px`. Populated after process().
    membrane_labels : np.ndarray
        Ring-shaped membrane region (expanded - nuclei). Populated after process().
    _processed : bool
        Whether process() has been called.
    """

    # Single shared model instance across all NucleiChannel objects
    # (avoids reloading weights on every instantiation)

    def __init__(self, raw: np.ndarray):
        self.raw = raw
        self.nuclei_labels: np.ndarray | None = None
        self.expanded_labels: np.ndarray | None = None
        self.membrane_labels: np.ndarray | None = None
        self._processed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, expansion_px: int = 15, min_area: int = 100,
                callback: Callable[[str], None] = None) -> "NucleiChannel":
        """
        Run the full nuclei processing pipeline:
          1. Normalise raw image.
          2. Segment nuclei with Cellpose.
          3. Filter nuclei by intensity and area.
          4. Expand labels to define membrane region.

        Parameters
        ----------
        expansion_px : int
            How many pixels to expand each nucleus outward to define the membrane ring.
        min_area : int
            Minimum nucleus area in pixels to retain.
        callback : function

        Returns
        -------
        self
        """
        if callback is None:
            callback = lambda x: None
        normalised = self._normalise(self.raw)
        callback("Segmenting nuclei")
        raw_labels = xu.segment_nuclei(normalised)
        callback("Filtering nuclei")
        self.nuclei_labels = self._filter_nuclei(raw_labels, self.raw, min_area)
        callback("Creating membranes")
        self.expanded_labels, self.membrane_labels = xu.create_membrane(
            self.nuclei_labels, expansion_px
        )
        self._processed = True
        return self

    @property
    def is_processed(self) -> bool:
        return self._processed


    @staticmethod
    def _normalise(img: np.ndarray) -> np.ndarray:
        """Shift image so minimum is zero ."""
        return img - img.min()


    @staticmethod
    def _filter_nuclei(labels: np.ndarray, raw: np.ndarray,
                       min_area: int) -> np.ndarray:
        """
        Keep only nuclei whose mean intensity exceeds (mean + std) of the
        raw image AND whose area exceeds min_area.
        """
        intensity_thresh = raw.mean() + raw.std()

        df = pd.DataFrame(measure.regionprops_table(
            labels, raw,
            properties=('label', 'area', 'mean_intensity')
        ))
        keep = df[
            (df['mean_intensity'] > intensity_thresh) &
            (df['area'] > min_area)
        ]

        mask = np.isin(labels, keep['label'])
        filtered = np.zeros_like(labels)
        filtered[mask] = labels[mask]
        return filtered



class TissueChannel:
    """
    Represents the chlorine (Cl) channel used to define tissue area.

    Attributes
    ----------
    raw : np.ndarray
        Raw intensity image.
    log_image : np.ndarray
        Log-transformed image. Populated after process().
    tissue_mask : np.ndarray
        Boolean mask — True where tissue is present. Populated after process().
    tissue_labels : np.ndarray
        Connected-component label image of the tissue mask. Populated after process().
    _processed : bool
        Whether process() has been called.
    """

    def __init__(self, raw: np.ndarray):
        self.raw = raw
        self.log_image: np.ndarray | None = None
        self.tissue_mask: np.ndarray | None = None
        self.tissue_labels: np.ndarray | None = None
        self._processed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, callback: Callable[[str], None] = None
                ) -> "TissueChannel":
        """
        Run the tissue processing pipeline:
          1. Log-transform the raw image.
          2. Threshold to produce a binary tissue mask.
          3. Label connected components.

        Returns
        -------
        self
        """
        if callback is not None:
            callback("Labeling tissues")
        self.log_image = xu.log_transform(self.raw)
        self.tissue_mask = self.log_image > 0
        self.tissue_labels = measure.label(self.tissue_mask, connectivity=2)
        self._processed = True
        return self

    @property
    def is_processed(self) -> bool:
        return self._processed

    def compute_tissue_stats(self, element_log: np.ndarray,
                             min_area: int = 20) -> tuple[float, float]:
        """
        Compute total tissue area and mean element intensity over tissue regions.

        Parameters
        ----------
        element_raw : np.ndarray
            Raw image of the element channel to measure intensity from.
        min_area : int
            Minimum region size (px) to include in the calculation.

        Returns
        -------
        (tissue_area, mean_intensity) : tuple[float, float]
        """
        if not self._processed:
            raise RuntimeError("Call process() before compute_tissue_stats().")

        df = pd.DataFrame(measure.regionprops_table(
            self.tissue_labels, element_log,
            properties=['area', 'mean_intensity']
        ))
        df = df[df['area'] > min_area]
        return float(df['area'].sum()), float(df['mean_intensity'].mean())
