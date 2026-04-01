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
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from stardist.models import StarDist2D
from csbdeep.utils import normalize
import tensorflow as tf
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))
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
# Clustering
# =============================================================================

def find_optimal_k(X: np.ndarray, min_k: int = 2, max_k: int = 8,
                   n_init: int = 100) -> int:
    """
    Find the number of KMeans clusters in [min_k, max_k] that maximises
    the silhouette score on a flattened image.

    Parameters
    ----------
    img : np.ndarray
        2-D image; will be flattened to a column vector internally.
    min_k, max_k : int
        Inclusive range of cluster counts to evaluate.
    n_init : int
        Number of KMeans random initialisations per k value.

    Returns
    -------
    int
        Optimal number of clusters.
    """
    #X = img.reshape(-1, 1)
    best_score, best_k = -1, min_k
    for k in range(min_k, max_k + 1):
        labels = KMeans(
            n_clusters=k, init='k-means++', max_iter=25, n_init=n_init
        ).fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_score, best_k = score, k
    return best_k


def run_kmeans(img: np.ndarray, n_clusters: int) -> np.ndarray:
    """
    Run KMeans on a 2-D image treated as a 1-D feature space.

    Parameters
    ----------
    img : np.ndarray
        2-D image.
    n_clusters : int
        Number of clusters.

    Returns
    -------
    np.ndarray
        Per-pixel cluster labels, same shape as `img`.
    """
    kmeans = KMeans(n_clusters=n_clusters, init='k-means++')
    kmeans.fit(img.reshape(-1, 1))
    return kmeans.labels_.reshape(img.shape)


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


