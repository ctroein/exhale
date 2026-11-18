"""Group raw abundance support by spatial proximity or ToMATo prominence without smoothing."""

from dataclasses import dataclass

import numpy as np

from ..data.clustering import ABUNDANCE_DEFAULTS

DEFAULT_MIN_CLUSTER_SIZE = ABUNDANCE_DEFAULTS["min_cluster_size"]
DEFAULT_RADIUS = ABUNDANCE_DEFAULTS["radius"]
DEFAULT_CUTOFF_SCALE = ABUNDANCE_DEFAULTS["cutoff_scale"]
DEFAULT_PROMINENCE = ABUNDANCE_DEFAULTS["prominence"]
ESTIMATE_CONTRAST_FRACTION = 0.10
MIN_ESTIMATED_MULTIPLE = 2.0
MAX_ESTIMATED_MULTIPLE = 15.0
METHOD_IDS = ("cutoff-proximity", "tomato")
_MAD_NORMALIZATION = 0.6744897501960817 * np.sqrt(2)


def validate_options(options, *, tomato=False):
    """Validate captured settings, including finite abundance overrides by element key."""
    minimum = options.get("min_cluster_size", DEFAULT_MIN_CLUSTER_SIZE)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, np.integer)) or minimum < 1:
        raise ValueError("Minimum cluster size must be a positive integer.")
    auto = options.get("auto_cutoff", False)
    if not isinstance(auto, bool):
        raise ValueError("Auto cutoff must be a boolean.")
    result = {"min_cluster_size": int(minimum), "auto_cutoff": auto}
    fields = [("radius", DEFAULT_RADIUS, 1), ("cutoff_scale", DEFAULT_CUTOFF_SCALE, 0)]
    if tomato:
        fields.append(("prominence", DEFAULT_PROMINENCE, 0))
    for key, default, lower in fields:
        value = options.get(key, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(value)
            or value < lower
        ):
            raise ValueError(
                f"{key.replace('_', ' ').capitalize()} must be finite and at least {lower}."
            )
        result[key] = float(value)
    for field in ("cutoff_scales", "thresholds"):
        values = options.get(field, {})
        if not isinstance(values, dict):
            raise ValueError("Cutoff overrides must be specified by element key.")
        for key, value in values.items():
            if (
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, (int, float, np.integer, np.floating))
                or not np.isfinite(value)
                or (field == "cutoff_scales" and value < 0)
            ):
                raise ValueError(
                    "Each cutoff override must have an element key and a finite valid value."
                )
        # Preserve absolute cutoffs from earlier saved runs using their original key.
        if values or field == "cutoff_scales":
            result[field] = {key: float(value) for key, value in values.items()}
    return result


def abundance_statistics(raw):
    """Return finite raw median and robust neighbor-difference scale, or None for no data.

    The scale is MAD of horizontal/vertical differences divided by
    0.6744897501960817 * sqrt(2). It describes local variation, including real
    structure; it is not an independently measured uncertainty or significance.
    """
    values = np.asarray(raw, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        return None
    with np.errstate(invalid="ignore", over="ignore"):
        differences = np.r_[np.diff(values, axis=0).ravel(), np.diff(values, axis=1).ravel()]
    differences = differences[np.isfinite(differences)]
    scale = (
        float(np.median(np.abs(differences - np.median(differences))) / _MAD_NORMALIZATION)
        if differences.size
        else 0.0
    )
    return float(np.median(values[finite])), scale


@dataclass(frozen=True)
class CutoffEstimate:
    """Contrast-relative abundance cutoff and its equivalent multiple of s."""

    baseline: float
    bright: float
    scale: float
    cutoff: float
    multiple: float | None
    window: tuple[int, int]
    contrast_cutoff: float
    uncapped_multiple: float | None
    fraction: float = ESTIMATE_CONTRAST_FRACTION


def estimate_cutoff(raw, minimum):
    """Estimate a contrast-relative cutoff with a multiple bounded to 2–15s.

    Use a near-square window covering at least the minimum cluster area, adapted
    to narrow maps. Only windows with at least that many finite observations
    contribute. The median is a background proxy, and the brightest window mean
    estimates supported high abundance. Use 10% of that contrast, bounding the equivalent multiple to 2–15s.
    Return None when the map cannot support a window or has no positive contrast.
    A zero s leaves the equivalent multiple undefined.
    """
    values = np.asarray(raw, dtype=np.float64)
    statistics = abundance_statistics(values)
    if statistics is None or values.size < minimum:
        return None
    height, width = values.shape
    side = int(np.ceil(np.sqrt(minimum)))
    rows, columns = min(height, side), min(width, side)
    columns = min(width, max(columns, int(np.ceil(minimum / rows))))
    rows = min(height, max(rows, int(np.ceil(minimum / columns))))
    finite = np.isfinite(values)

    def window_sums(array):
        integral = np.pad(array.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
        return (
            integral[rows:, columns:]
            - integral[:-rows, columns:]
            - integral[rows:, :-columns]
            + integral[:-rows, :-columns]
        )

    counts = window_sums(finite.astype(np.int64))
    supported = counts >= minimum
    if not supported.any():
        return None
    sums = window_sums(np.where(finite, values, 0))
    bright = float(np.max(sums[supported] / counts[supported]))
    baseline, scale = statistics
    contrast = ESTIMATE_CONTRAST_FRACTION * (bright - baseline)
    contrast_cutoff = baseline + contrast
    if not np.isfinite(contrast_cutoff) or bright <= baseline:
        return None
    uncapped = contrast / scale if scale > 0 else None
    multiple = (
        min(MAX_ESTIMATED_MULTIPLE, max(MIN_ESTIMATED_MULTIPLE, uncapped))
        if uncapped is not None
        else None
    )
    cutoff = baseline + multiple * scale if multiple is not None else contrast_cutoff
    return CutoffEstimate(
        baseline, bright, scale, cutoff, multiple, (rows, columns), contrast_cutoff, uncapped
    )


def _neighbors(support, radius, callback):
    """Build only candidate-pixel neighbors; links never add intermediate pixels."""
    coordinates = np.argwhere(support)
    mapping = np.full(support.shape, -1, dtype=np.intp)
    mapping[tuple(coordinates.T)] = np.arange(len(coordinates))
    bound = int(np.floor(radius))
    # Offsets larger than the image cannot connect any observations.
    height, width = support.shape
    offsets = [
        (dy, dx)
        for dy in range(-min(bound, height - 1), min(bound, height - 1) + 1)
        for dx in range(-min(bound, width - 1), min(bound, width - 1) + 1)
        if 0 < dy * dy + dx * dx <= radius * radius
    ]
    adjacency = np.full((len(coordinates), len(offsets)), -1, dtype=np.intp)
    for column, (dy, dx) in enumerate(offsets):
        if column % 16 == 0:
            callback("Building abundance proximity graph")
        y, x = coordinates[:, 0] + dy, coordinates[:, 1] + dx
        valid = (y >= 0) & (y < height) & (x >= 0) & (x < width)
        adjacency[valid, column] = mapping[y[valid], x[valid]]
    return coordinates, adjacency


def cluster_channel(raw, name, options, *, method_id, threshold=None, callback=lambda _text: None):
    """Measure proximity or prominence groups while preserving fragmented cluster IDs."""
    import pandas as pd
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    from skimage.measure import regionprops_table

    from ..xrf_refcopy.xrf_element_channel import ElementChannel

    if method_id not in METHOD_IDS:
        raise ValueError(f"Unknown abundance clustering method: {method_id}")
    options = validate_options(options, tomato=method_id == "tomato")
    raw = np.asarray(raw)
    if raw.ndim != 2 or not raw.size:
        raise ValueError("Abundance clustering requires a nonempty two-dimensional element map.")
    valid = np.isfinite(raw)
    labels = np.zeros(raw.shape, dtype=np.int32)
    channel = ElementChannel(name, raw)
    callback(f"{name}: estimating raw-abundance support")
    statistics = abundance_statistics(raw)
    cutoff = threshold
    if statistics is not None:
        median, scale = statistics
        if cutoff is None:
            cutoff = median + options["cutoff_scale"] * scale
        support = valid & (raw > cutoff)
        callback(
            f"{name}: abundance > {cutoff:.8g}; s = {scale:.8g}; {support.sum()} candidate pixels"
        )
        if support.sum() >= options["min_cluster_size"]:
            coordinates, adjacency = _neighbors(support, options["radius"], callback)
            callback(f"{name}: grouping abundant pixels")
            if method_id == "tomato":
                try:
                    from gudhi.clustering.tomato import Tomato
                except ImportError as error:
                    raise RuntimeError(
                        "ToMATo requires GUDHI; install Exhale's updated dependencies."
                    ) from error
                model = Tomato(graph_type="manual", density_type="manual")
                model.fit([row[row >= 0] for row in adjacency], weights=raw[support])
                callback(f"{name}: applying prominence {options['prominence']:g}s")
                model.merge_threshold_ = options["prominence"] * scale
                assignments = model.labels_
            else:
                rows, columns = np.nonzero(adjacency >= 0)
                graph = csr_matrix(
                    (np.ones(len(rows), dtype=np.uint8), (rows, adjacency[rows, columns])),
                    shape=(len(coordinates), len(coordinates)),
                )
                _, assignments = connected_components(graph, directed=False)
            callback(f"{name}: measuring abundance clusters")
            counts = np.bincount(assignments)
            retained = np.flatnonzero(counts >= options["min_cluster_size"])
            renumber = np.zeros(len(counts), dtype=np.int32)
            renumber[retained] = np.arange(1, len(retained) + 1)
            labels[tuple(coordinates.T)] = renumber[assignments]
    channel.intensity_thresholds = np.array([] if cutoff is None else [cutoff])
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


def compute(arrays, job, parameters, callback, *, method_id, progress=None, previous=None):
    """Process each captured element independently and retain actual abundance cutoffs."""
    from ..xrf_refcopy.xrf_sample_class import XRFSample

    options = validate_options(parameters.method_options, tomato=method_id == "tomato")
    sample = XRFSample(job.sample_name)
    for index, (key, name, raw) in enumerate(zip(job.keys, job.names, arrays, strict=True)):
        if progress is not None:
            progress(index, len(arrays), name)
        callback(f"Clustering {name} with {method_id}")
        try:
            multiple = options["cutoff_scales"].get(key, options["cutoff_scale"])
            threshold = options.get("thresholds", {}).get(key)
            if key in options["cutoff_scales"]:
                threshold = None
            elif threshold is None and options["auto_cutoff"]:
                callback(f"Estimating cutoff for {name}")
                estimate = estimate_cutoff(raw, options["min_cluster_size"])
                if estimate is not None and estimate.multiple is not None:
                    multiple = estimate.multiple
            effective_threshold = threshold
            statistics = abundance_statistics(raw)
            if effective_threshold is None and statistics is not None:
                effective_threshold = statistics[0] + multiple * statistics[1]
            reusable = None
            if previous is not None and job.refs[index] in previous.element_refs:
                old_options = previous.parameters.method_options
                old_options = old_options.get("map_defaults", {}).get(key, old_options)
                old_options = validate_options(old_options, tomato=method_id == "tomato")
                old_channel = tuple(previous.xrf_sample.elements.values())[
                    previous.element_refs.index(job.refs[index])
                ]
                old_thresholds = old_channel.intensity_thresholds
                if (
                    all(
                        old_options.get(field) == options.get(field)
                        for field in ("min_cluster_size", "radius", "prominence")
                    )
                    and old_thresholds is not None
                    and len(old_thresholds) == 1
                    and effective_threshold == old_thresholds[0]
                ):
                    reusable = old_channel
            if reusable is not None:
                callback(f"{name}: reusing clusters with the same parameters")
                sample.elements[key] = reusable
            else:
                sample.elements[key] = cluster_channel(
                    raw,
                    name,
                    {**options, "cutoff_scale": multiple},
                    method_id=method_id,
                    threshold=threshold,
                    callback=callback,
                )
        except ValueError as error:
            raise ValueError(f"{name} ({key}): {error}") from error
        if progress is not None:
            progress(index + 1, len(arrays), name)
    return sample
