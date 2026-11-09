"""Cluster positions of raw-abundance-selected pixels without smoothing or gap filling."""

import numpy as np

DEFAULT_MIN_CLUSTER_SIZE = 20
DEFAULT_MIN_SAMPLES = 5
HISTOGRAM_BINS = 256


def validate_options(options):
    """Return validated numerical settings and finite per-element abundance cutoffs."""
    minimum = options.get("min_cluster_size", DEFAULT_MIN_CLUSTER_SIZE)
    support = options.get("min_samples", DEFAULT_MIN_SAMPLES)
    for name, value, lower in (
        ("Minimum cluster size", minimum, 2),
        ("Density support", support, 1),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < lower:
            raise ValueError(f"{name} must be an integer of at least {lower}.")
    thresholds = options.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ValueError("Abundance thresholds must be specified by element key.")
    for key, value in thresholds.items():
        if (
            not isinstance(key, str)
            or not key
            or isinstance(value, bool)
            or not isinstance(value, (float, int, np.floating, np.integer))
            or not np.isfinite(value)
        ):
            raise ValueError("Each abundance threshold must have an element key and finite value.")
    return int(minimum), int(support), dict(thresholds)


def cluster_channel(raw, name, *, minimum, support, threshold=None, callback=lambda _text: None):
    """Return a measured channel; disconnected pixels retain their shared cluster ID.

    Automatic thresholds use a 256-bin Otsu histogram of finite raw abundances.
    Values strictly above the cutoff enter HDBSCAN as equally weighted positions.
    Uniform images have no pixels above their automatic cutoff. Non-finite pixels
    and HDBSCAN noise remain background. Cancellation is checked before and after
    the estimator call; scikit-learn's fit itself has no cancellation callback.
    """
    import pandas as pd
    from skimage.filters import threshold_otsu
    from skimage.measure import regionprops_table
    from sklearn.cluster import HDBSCAN

    from ..xrf_refcopy.xrf_element_channel import ElementChannel

    raw = np.asarray(raw)
    if raw.ndim != 2 or not raw.size:
        raise ValueError("HDBSCAN requires a nonempty two-dimensional element map.")
    valid = np.isfinite(raw)
    values = raw[valid].astype(np.float64, copy=False)
    channel = ElementChannel(name, raw)
    labels = np.zeros(raw.shape, dtype=np.int32)
    if values.size:
        cutoff = (
            float(threshold_otsu(values, nbins=HISTOGRAM_BINS))
            if threshold is None
            else float(threshold)
        )
        channel.intensity_thresholds = np.array([cutoff])
        coordinates = np.argwhere(valid & (raw > cutoff))
        count = len(coordinates)
        callback(f"{name}: abundance > {cutoff:.8g}; {count} candidate pixels")
        if count >= max(minimum, support):
            assignments = HDBSCAN(
                min_cluster_size=minimum,
                min_samples=support,
                metric="euclidean",
                cluster_selection_method="eom",
                allow_single_cluster=True,
                copy=False,
            ).fit_predict(coordinates)
            callback(f"{name}: measuring HDBSCAN clusters")
            # Do not connected-component-label this map: a cluster may have gaps.
            labels[tuple(coordinates.T)] = np.maximum(assignments + 1, 0)
    else:
        channel.intensity_thresholds = np.array([])
        callback(f"{name}: no finite abundance measurements")
    channel.cluster_labels = labels
    channel.cluster_df = pd.DataFrame(
        regionprops_table(
            labels,
            intensity_image=raw if valid.all() else np.where(valid, raw, 0),
            properties=("label", "area", "mean_intensity", "centroid"),
        )
    )
    channel._processed = True
    return channel


def compute(arrays, job, parameters, callback, *, progress=None):
    """Process a captured sample using per-element cutoffs and independent spatial clustering."""
    from ..xrf_refcopy.xrf_sample_class import XRFSample

    minimum, support, thresholds = validate_options(parameters.method_options)
    sample = XRFSample(job.sample_name)
    for index, (key, name, raw) in enumerate(zip(job.keys, job.names, arrays, strict=True)):
        if progress is not None:
            progress(index, len(arrays), name)
        callback(f"Clustering {name} with HDBSCAN")
        try:
            sample.elements[key] = cluster_channel(
                raw,
                name,
                minimum=minimum,
                support=support,
                threshold=thresholds.get(key),
                callback=callback,
            )
        except ValueError as error:
            raise ValueError(f"{name} ({key}): {error}") from error
        if progress is not None:
            progress(index + 1, len(arrays), name)
    return sample
