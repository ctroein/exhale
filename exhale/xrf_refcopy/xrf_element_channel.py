import numpy as np
import pandas as pd
from . import xrf_utils as xu
from collections.abc import Callable

#import xrf_clustering as xc

class ElementChannel:
    """
    Represents a single element channel (e.g. Ca, Cu, Fe, Zn) for one XRF sample.

    Attributes
    ----------
    name : str
        Element name (e.g. 'Ca').
    raw : np.ndarray
        Raw intensity image as loaded from file.
    log_image : np.ndarray
        Log-transformed, mean-subtracted image. Populated after process().
    cluster_labels : np.ndarray
        Labelled image of detected clusters. Populated after process().
    cluster_df : pd.DataFrame
        Per-cluster properties (area, mean_intensity, centroid). Populated after process().
    _processed : bool
        Whether process() has been called.
    """

    def __init__(self, name: str, raw: np.ndarray):
        self.name = name
        self.raw = raw
        self.log_image: np.ndarray | None = None
        self.cluster_labels: np.ndarray | None = None
        self.cluster_df: pd.DataFrame | None = None
        self._processed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, min_k: int = 3, max_k: int = 5, n_init: int = 100,
                max_cluster_size: int = 10_000, min_area: int = 1,
                callback: Callable[[str], None] = None
                ) -> "ElementChannel":
        """
        Run the full processing pipeline:
          1. Log-transform the raw image.
          2. Estimate the optimal number of clusters.
          3. Run KMeans and extract cluster properties.

        Parameters
        ----------
        min_k, max_k : int
            Range of cluster counts to evaluate.
        n_init : int
            Number of KMeans initialisations per k (higher = more stable).
        max_cluster_size : int
            Clusters larger than this (px) are treated as background and ignored.
        min_area : int
            Minimum connected-component area to keep after segmentation.

        Returns
        -------
        self  (allows chaining: channel.process().cluster_df)
        """
        if callback is None:
            callback = lambda x: None

        callback(f"Processing element {self.name}")
        self.log_image = xu.log_transform(self.raw)
        n_clusters = xu.find_optimal_k(self.log_image, min_k, max_k, n_init,
                                       callback=callback)
        self.cluster_labels, self.cluster_df = self._run_pipeline(
            self.log_image, n_clusters, self.raw,
            max_cluster_size=max_cluster_size, min_area=min_area,
            callback=callback
        )
        self._processed = True
        return self

    @property
    def is_processed(self) -> bool:
        return self._processed

    # ------------------------------------------------------------------
    # Full pipeline (private)
    # ------------------------------------------------------------------

    def _run_pipeline(self, log_img: np.ndarray, n_clusters: int,
                      raw_img: np.ndarray, max_cluster_size: int,
                      min_area: int,
                      callback: Callable[[str], None]
                      ) -> tuple[np.ndarray, pd.DataFrame]:
        callback("Running K-means")
        k_labels = xu.run_kmeans(log_img, n_clusters)
        callback("Extracting masks")
        mask = xu.extract_small_cluster_mask(k_labels, max_cluster_size)
        callback("Building segmented image")
        segmented = xu.build_segmented_image(log_img.shape, mask)
        labels, df = xu.compute_region_properties(segmented, raw_img, min_area)
        cluster_labels = xu.draw_filtered_labels(labels, df)
        return cluster_labels, df

