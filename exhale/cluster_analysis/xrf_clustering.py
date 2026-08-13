"""Compatibility helpers for the legacy cluster-analysis pipeline.

Intensity clustering is implemented by the deterministic weighted 1-D
partitioner in :mod:`exhale.xrf_refcopy.xrf_utils`.
"""
import numpy as np
import pandas as pd
from skimage import measure

from ..xrf_refcopy import xrf_utils as xu


def run_clustering(X, min_k=3, max_k=5, n_init=1):
    """Return the best exact contiguous intensity partition size."""
    return xu.find_optimal_k(X, min_k, max_k, n_init)


def measure_number_cluster_legacy(image, num_runs=100):
    """Compatibility alias; repeated random runs are no longer needed."""
    return xu.find_optimal_k(image)


def measure_number_cluster(X, min_k=3, max_k=5, n_init=100):
    """Find the best exact weighted 1-D partition size."""
    return xu.find_optimal_k(X, min_k, max_k, n_init)


def run_kmeans(img, num_clusters, return_thresholds=False):
    """Compatibility wrapper for deterministic intensity thresholding."""
    return xu.run_kmeans(img, num_clusters, return_thresholds)


def extract_cluster_positions(labels, max_cluster_size=10000):
    """Return coordinates of intensity classes smaller than ``max_cluster_size``."""
    positions = {}
    for label, size in enumerate(np.bincount(labels.ravel())):
        if size <= max_cluster_size:
            positions[label] = np.column_stack(np.where(labels == label))
    return positions


def build_mask(img_shape, cluster_positions):
    """Build a mask from the selected intensity-class coordinates."""
    mask = np.zeros(img_shape, dtype=bool)
    for positions in cluster_positions.values():
        mask[tuple(positions.T)] = True
    return mask


def compute_cluster_properties(segmented_img, raw_img, min_area=1):
    """Measure and filter connected components in a binary cluster mask."""
    labels = measure.label(segmented_img, connectivity=2)
    props = measure.regionprops_table(
        labels, raw_img,
        properties=["label", "area", "mean_intensity", "centroid"])
    df = pd.DataFrame(props)
    return labels, df[df["area"] > min_area]


def measure_clusters_properties(img, num_clusters, raw_img,
                                max_cluster_size=10000):
    """Threshold intensities and extract properties of retained components."""
    k_labels = xu.run_kmeans(img, num_clusters)
    mask = xu.extract_small_cluster_mask(k_labels, max_cluster_size)
    segmented = xu.build_segmented_image(img.shape, mask)
    labels, filtered_df = compute_cluster_properties(segmented, raw_img)
    return xu.draw_filtered_labels(labels, filtered_df), filtered_df


def measure_clusters_properties_v2(img, num_clusters, raw_img,
                                   max_cluster_size=10000):
    """Legacy entry point retained for callers of ``xrf_main``."""
    return measure_clusters_properties(
        img, num_clusters, raw_img, max_cluster_size=max_cluster_size)
