"""
xrf_utils.py
------------
Stateless utility functions shared across XRF channel classes.

All functions are pure (no side effects, no class dependencies) and can be
imported individually wherever needed — including notebooks and future modules.
"""
import os
import numpy as np
import pandas as pd
from skimage import measure
from skimage.segmentation import expand_labels
from collections.abc import Callable
from dataclasses import dataclass

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "1")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
from stardist.models import StarDist2D
from csbdeep.utils import normalize
#import tensorflow as tf
#print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))
model = None
_model_basedir = '.'

# =============================================================================
# Image transformation
# =============================================================================

def log_transform(img: np.ndarray) -> np.ndarray:
    """
    Log-transform inspired by Fiji's 'Log' function.

    Scales the image to [0, 255] using a logarithmic curve, subtracts the
    mean, and clips negative values to zero. Preserves the input dtype.

    Parameters
    ----------
    img : np.ndarray
        Raw intensity image (any numeric dtype).

    Returns
    -------
    np.ndarray
        Transformed image, same dtype as input.
    """
    c = 255 / np.log1p(img.max())
    log_image = c * np.log1p(img.astype(np.float32))
    return np.clip(log_image - log_image.mean(), 0, None).astype(img.dtype)


# =============================================================================
# Label / mask operations
# =============================================================================

def set_model_basedir(path):
    global model, _model_basedir
    if model is not None and path != _model_basedir:
        raise RuntimeError(f"Model already loaded from {_model_basedir}")
    _model_basedir = path

def load_model():
    global model
    if model is None:
        model = StarDist2D(
            None, '2D_versatile_fluo_copy', basedir=_model_basedir)

def segment_nuclei(img_nuclei):
    load_model()
    # Run deep learning segmentation model on nuclei channel
    labels, _ = model.predict_instances(normalize(img_nuclei)) #labels, flows, styles = model.eval(img_nuclei, diameter=None, channels=[0,0]) #
    return labels


def create_membrane(
    labels_nuclei: np.ndarray,
    expansion_size: int = 15,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Expand nucleus labels and derive a membrane ring.

    Returns
    -------
    expanded_labels : labels grown by *expansion_size* pixels
    membrane_labels : ring between expanded and original labels
    """
    expanded = expand_labels(labels_nuclei, distance=expansion_size)
    membrane = expanded - labels_nuclei
    return expanded, membrane


def draw_filtered_labels(labels: np.ndarray, df: pd.DataFrame,
                         label_col: str = 'label') -> np.ndarray:
    """
    Zero out any region in `labels` whose ID is not present in `df`.

    Parameters
    ----------
    labels : np.ndarray
        Integer label image (e.g. from skimage.measure.label).
    df : pd.DataFrame
        DataFrame containing a column of label IDs to keep.
    label_col : str
        Name of the column in `df` that holds label IDs.

    Returns
    -------
    np.ndarray
        Filtered label image; same shape and dtype as `labels`.
    """
    mask = np.isin(labels, df[label_col])
    filtered = np.zeros_like(labels)
    filtered[mask] = labels[mask]
    return filtered


def build_segmented_image(shape: tuple, mask: np.ndarray) -> np.ndarray:
    """
    Create a binary uint8 image from a boolean mask.

    Parameters
    ----------
    shape : tuple
        Output image shape.
    mask : np.ndarray
        Boolean mask; True pixels are set to 1 in the output.

    Returns
    -------
    np.ndarray  (dtype=uint8)
    """
    seg = np.zeros(shape, dtype=np.uint8)
    seg[mask] = 1
    return seg


def filter_labels_by_intensity(labels: np.ndarray, raw: np.ndarray,
                                min_area: int = 1,
                                intensity_thresh: float | None = None
                                ) -> np.ndarray:
    """
    Keep only labelled regions that exceed an area and intensity threshold.

    If `intensity_thresh` is None, defaults to mean + std of `raw`.

    Parameters
    ----------
    labels : np.ndarray
        Integer label image.
    raw : np.ndarray
        Intensity image used for thresholding.
    min_area : int
        Minimum region area in pixels.
    intensity_thresh : float | None
        Minimum mean intensity. Defaults to raw.mean() + raw.std().

    Returns
    -------
    np.ndarray
        Filtered label image.
    """
    if intensity_thresh is None:
        intensity_thresh = raw.mean() + raw.std()

    df = pd.DataFrame(measure.regionprops_table(
        labels, raw,
        properties=('label', 'area', 'mean_intensity')
    ))
    keep = df[
        (df['mean_intensity'] > intensity_thresh) &
        (df['area'] > min_area)
    ]
    return draw_filtered_labels(labels, keep)


# =============================================================================
# Region properties
# =============================================================================

def compute_region_properties(segmented: np.ndarray, intensity: np.ndarray,
                               min_area: int = 1,
                               extra_properties: tuple = ()
                               ) -> tuple[np.ndarray, pd.DataFrame]:
    """
    Label connected components in `segmented` and compute region properties.

    Parameters
    ----------
    segmented : np.ndarray
        Binary image (0 = background, 1 = foreground).
    intensity : np.ndarray
        Intensity image used for mean_intensity measurement.
    min_area : int
        Minimum region area to retain in the output dataframe.
    extra_properties : tuple of str
        Additional skimage regionprops property names to include.

    Returns
    -------
    (label_image, dataframe) : tuple[np.ndarray, pd.DataFrame]
        label_image has the same shape as `segmented`.
        dataframe contains at least: label, area, mean_intensity, centroid-0, centroid-1.
    """
    base_props = ('label', 'area', 'mean_intensity', 'centroid')
    all_props = base_props + tuple(
        p for p in extra_properties if p not in base_props
    )

    labels = measure.label(segmented, connectivity=2)
    props = measure.regionprops_table(labels, intensity, properties=all_props)
    df = pd.DataFrame(props)
    return labels, df[df['area'] > min_area].reset_index(drop=True)


# =============================================================================
# One-dimensional intensity clustering
# =============================================================================

@dataclass(frozen=True)
class IntensityPartition:
    """Exact contiguous partition of a one-dimensional intensity histogram."""
    k: int
    thresholds: np.ndarray
    labels: np.ndarray
    silhouette_score: float


def _coarsen_histogram(values: np.ndarray, counts: np.ndarray,
                       max_bins: int | None = None
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Merge consecutive intensity values into weighted, adaptive histogram bins.

    The target number of bins defaults to ``pixel_count ** (2 / 3)``.  Bin
    edges follow cumulative pixel count, never split an input intensity value,
    and retain the original low/high values so output thresholds can still be
    placed on the original intensity axis.
    """
    if max_bins is None:
        max_bins = max(2, round(int(counts.sum()) ** (2 / 3)))
    if values.size <= max_bins:
        return values, counts, values, values

    cumulative = np.cumsum(counts)
    targets = np.arange(1, max_bins) * cumulative[-1] / max_bins
    stops = np.unique(np.r_[
        0, np.searchsorted(cumulative, targets, side="left") + 1, values.size])
    starts = stops[:-1]
    stops = stops[1:]
    bin_counts = np.add.reduceat(counts, starts)
    bin_sums = np.add.reduceat(counts * values, starts)
    return (bin_sums / bin_counts, bin_counts,
            values[starts], values[stops - 1])


def _intensity_histogram(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values, counts = np.unique(np.asarray(img).ravel(), return_counts=True)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("Intensity image must contain only finite values")
    return values.astype(float, copy=False), counts.astype(np.int64, copy=False)


def _segment_cost(prefix_w, prefix_wx, prefix_wx2, start, stop) -> float:
    """Weighted within-segment squared error for histogram bins [start, stop)."""
    weight = prefix_w[stop] - prefix_w[start]
    total = prefix_wx[stop] - prefix_wx[start]
    total_sq = prefix_wx2[stop] - prefix_wx2[start]
    return max(0.0, total_sq - total * total / weight)


def _optimal_cuts_by_k(values: np.ndarray, counts: np.ndarray,
                       max_k: int) -> list[np.ndarray]:
    """Return optimal cuts for every group count up to ``max_k`` in one DP."""
    n = values.size
    prefix_w = np.r_[0.0, np.cumsum(counts, dtype=float)]
    prefix_wx = np.r_[0.0, np.cumsum(counts * values, dtype=float)]
    prefix_wx2 = np.r_[0.0, np.cumsum(counts * values * values, dtype=float)]

    previous = np.full(n + 1, np.inf)
    previous[0] = 0.0
    cuts = np.zeros((max_k + 1, n + 1), dtype=np.intp)

    for groups in range(1, max_k + 1):
        current = np.full(n + 1, np.inf)

        def fill(left, right, opt_left, opt_right):
            if left > right:
                return
            middle = (left + right) // 2
            best_cost = np.inf
            best_cut = -1
            upper = min(middle - 1, opt_right)
            for cut in range(opt_left, upper + 1):
                cost = previous[cut] + _segment_cost(
                    prefix_w, prefix_wx, prefix_wx2, cut, middle)
                if cost < best_cost:
                    best_cost, best_cut = cost, cut
            current[middle] = best_cost
            cuts[groups, middle] = best_cut
            fill(left, middle - 1, opt_left, best_cut)
            fill(middle + 1, right, best_cut, opt_right)

        fill(groups, n, groups - 1, n - 1)
        previous = current

    result = [np.array([0], dtype=np.intp)]
    for k in range(1, max_k + 1):
        boundaries = np.empty(k + 1, dtype=np.intp)
        boundaries[k] = n
        for groups in range(k, 0, -1):
            boundaries[groups - 1] = cuts[groups, boundaries[groups]]
        result.append(boundaries)
    return result


def _optimal_cuts(values: np.ndarray, counts: np.ndarray, k: int) -> np.ndarray:
    """Return optimal cut indices for one group count."""
    return _optimal_cuts_by_k(values, counts, k)[k]


def _weighted_silhouette(values, counts, boundaries) -> float:
    """Exact weighted silhouette for ordered histogram intervals.

    In one dimension, the closest other interval is always the immediate left
    or right neighbour.  Prefix sums make all mean distances vectorized over
    the values in an interval, without expanding pixel counts.
    """
    k = len(boundaries) - 1
    prefix_w = np.r_[0.0, np.cumsum(counts, dtype=float)]
    prefix_wx = np.r_[0.0, np.cumsum(counts * values, dtype=float)]
    total_weight = prefix_w[-1]

    score = 0.0
    for group in range(k):
        start, stop = boundaries[group:group + 2]
        own_weight = prefix_w[stop] - prefix_w[start]
        if own_weight == 1:
            # Match the usual silhouette convention for singleton clusters.
            continue

        x = values[start:stop]
        weights = counts[start:stop]
        # Sum |x_i - x_j| over this interval, excluding equal-valued pixels
        # (whose distance is zero), then divide by N - 1 for a_i.
        left_w = prefix_w[start:stop] - prefix_w[start]
        left_x = prefix_wx[start:stop] - prefix_wx[start]
        right_w = prefix_w[stop] - prefix_w[start + 1:stop + 1]
        right_x = prefix_wx[stop] - prefix_wx[start + 1:stop + 1]
        a = (x * left_w - left_x + right_x - x * right_w) / (own_weight - 1)

        distances = []
        if group:
            left_start, left_stop = boundaries[group - 1:group + 1]
            left_weight = prefix_w[left_stop] - prefix_w[left_start]
            distances.append(
                (x * left_weight - (prefix_wx[left_stop] - prefix_wx[left_start])) /
                left_weight)
        if group + 1 < k:
            right_start, right_stop = boundaries[group + 1:group + 3]
            right_weight = prefix_w[right_stop] - prefix_w[right_start]
            distances.append(
                ((prefix_wx[right_stop] - prefix_wx[right_start]) - x * right_weight) /
                right_weight)
        b = distances[0] if len(distances) == 1 else np.minimum(*distances)
        denominator = np.maximum(a, b)
        silhouette = np.divide(
            b - a, denominator, out=np.zeros_like(a), where=denominator != 0)
        score += np.dot(weights, silhouette)
    return score / total_weight


def _partition_histogram(values: np.ndarray, counts: np.ndarray,
                         n_clusters: int,
                         boundaries: np.ndarray | None = None,
                         bin_lows: np.ndarray | None = None,
                         bin_highs: np.ndarray | None = None,
                         ) -> tuple[np.ndarray, float]:
    """Return thresholds and silhouette score for one histogram partition."""
    if not 2 <= n_clusters <= values.size:
        raise ValueError(
            f"n_clusters must be between 2 and {values.size} distinct intensities")
    if boundaries is None:
        boundaries = _optimal_cuts(values, counts, n_clusters)
    cuts = boundaries[1:-1]
    if bin_lows is None:
        bin_lows = values
    if bin_highs is None:
        bin_highs = values
    thresholds = bin_highs[cuts - 1] + (
        bin_lows[cuts] - bin_highs[cuts - 1]) / 2
    return thresholds, _weighted_silhouette(values, counts, boundaries)


def partition_intensities(img: np.ndarray, n_clusters: int,
                          max_histogram_bins: int | None = None
                          ) -> IntensityPartition:
    """Partition intensity values into contiguous weighted intervals.

    Histograms with more than ``max_histogram_bins`` values are adaptively
    coarsened first.  The default is ``pixel_count ** (2 / 3)`` bins.
    """
    values, counts = _intensity_histogram(img)
    values, counts, bin_lows, bin_highs = _coarsen_histogram(
        values, counts, max_histogram_bins)
    thresholds, score = _partition_histogram(
        values, counts, n_clusters, bin_lows=bin_lows, bin_highs=bin_highs)
    labels = np.searchsorted(thresholds, img, side="right").astype(np.intp)
    return IntensityPartition(
        k=n_clusters,
        thresholds=thresholds,
        labels=labels,
        silhouette_score=score,
    )


def find_optimal_partition(
        img: np.ndarray, min_k: int = 2, max_k: int = 8,
        callback: Callable[[str], None] = None,
        max_histogram_bins: int | None = None) -> IntensityPartition:
    """Select the best weighted 1-D partition over an adaptive histogram."""
    values, counts = _intensity_histogram(img)
    values, counts, bin_lows, bin_highs = _coarsen_histogram(
        values, counts, max_histogram_bins)
    min_k = max(2, min_k)
    max_k = min(max_k, values.size)
    if min_k > max_k:
        raise ValueError(
            "No valid cluster counts: need at least two distinct intensities")

    if callback is not None:
        callback(
            f"Selecting optimal intensity thresholds ({min_k} to {max_k} groups)")
    optimal_cuts = _optimal_cuts_by_k(values, counts, max_k)
    best_k = None
    best_thresholds = None
    best_score = -np.inf
    for k in range(min_k, max_k + 1):
        thresholds, score = _partition_histogram(
            values, counts, k, boundaries=optimal_cuts[k],
            bin_lows=bin_lows, bin_highs=bin_highs)
        if score > best_score:
            best_k, best_thresholds, best_score = k, thresholds, score
    labels = np.searchsorted(best_thresholds, img, side="right").astype(np.intp)
    return IntensityPartition(best_k, best_thresholds, labels, best_score)


def find_optimal_k(X: np.ndarray, min_k: int = 2, max_k: int = 8,
                   n_init: int = 100,
                   callback: Callable[[str], None] = None) -> int:
    """Return the best exact 1-D intensity partition size.

    ``n_init`` is retained for compatibility and has no effect: this method is
    deterministic and does not use random initialisation.
    """
    return find_optimal_partition(X, min_k, max_k, callback).k


def run_kmeans(img: np.ndarray, n_clusters: int,
               return_thresholds: bool = False):
    """Compatibility wrapper for exact 1-D intensity thresholding.

    Set ``return_thresholds`` to also receive the boundaries between labels.
    """
    partition = partition_intensities(img, n_clusters)
    if return_thresholds:
        return partition.labels, partition.thresholds
    return partition.labels


def extract_small_cluster_mask(k_labels: np.ndarray,
                                max_cluster_size: int = 100000) -> np.ndarray:
    """
    Build a boolean mask for pixels belonging to clusters below a size threshold.

    Clusters larger than `max_cluster_size` are assumed to be background and
    excluded from the mask.

    Parameters
    ----------
    k_labels : np.ndarray
        Per-pixel cluster label array (output of run_kmeans).
    max_cluster_size : int
        Maximum cluster size (in pixels) to retain.

    Returns
    -------
    np.ndarray  (dtype=bool)
    """
    cluster_sizes = np.bincount(k_labels.ravel())
    mask = np.zeros(k_labels.shape, dtype=bool)
    for label, size in enumerate(cluster_sizes):
        if size <= max_cluster_size:
            mask[k_labels == label] = True
    return mask
