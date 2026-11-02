"""Legacy region containers and tissue-mask processing for element clustering."""

from collections.abc import Callable

import numpy as np
import pandas as pd
from skimage import measure


class NucleiChannel:
    """Hold nucleus-region data retained in existing clustering sidecars.

    Segmentation backends use their own output model and never call this class.
    """

    def __init__(self, raw: np.ndarray):
        self.raw = raw
        self.nuclei_labels: np.ndarray | None = None
        self.expanded_labels: np.ndarray | None = None
        self.membrane_labels: np.ndarray | None = None
        self._processed = False

    @property
    def is_processed(self) -> bool:
        return self._processed


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

    def process(self, callback: Callable[[str], None] = None) -> "TissueChannel":
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
        from . import xrf_utils as xu

        self.log_image = xu.log_transform(self.raw)
        self.tissue_mask = self.log_image > 0
        self.tissue_labels = measure.label(self.tissue_mask, connectivity=2)
        self._processed = True
        return self

    @property
    def is_processed(self) -> bool:
        return self._processed

    def compute_tissue_stats(
        self, element_log: np.ndarray, min_area: int = 20
    ) -> tuple[float, float]:
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

        df = pd.DataFrame(
            measure.regionprops_table(
                self.tissue_labels, element_log, properties=["area", "mean_intensity"]
            )
        )
        df = df[df["area"] > min_area]
        return float(df["area"].sum()), float(df["mean_intensity"].mean())
