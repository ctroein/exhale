"""Regression tests for deterministic one-dimensional intensity clustering."""

from time import perf_counter

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from exhale.xrf_refcopy import xrf_utils as xu


def test_histogram_partition_matches_seeded_kmeans_search():
    """The exact weighted partition agrees with the former 1-D KMeans search."""
    rng = np.random.default_rng(1729)
    intensities = np.concatenate(
        (
            rng.normal(20, 2.0, 600),
            rng.normal(65, 4.0, 450),
            rng.normal(125, 3.0, 300),
        )
    )
    image = np.rint(np.clip(intensities, 0, 255)).astype(np.uint8).reshape(45, 30)
    flat = image.reshape(-1, 1)

    started = perf_counter()
    partition = xu.find_optimal_partition(image, min_k=2, max_k=5)
    exact_seconds = perf_counter() - started

    # Fixed data and seed make this a stable regression value.
    assert partition.k == 3
    assert partition.silhouette_score == pytest.approx(0.9305032780974145)

    old_best_score = -np.inf
    old_best_k = None
    old_best_model = None
    started = perf_counter()
    for k in range(2, 6):
        model = KMeans(
            n_clusters=k,
            init="k-means++",
            max_iter=25,
            n_init=100,
            random_state=1729,
        ).fit(flat)
        score = silhouette_score(flat, model.labels_)
        if score > old_best_score:
            old_best_score, old_best_k, old_best_model = score, k, model
    kmeans_seconds = perf_counter() - started

    assert old_best_k == partition.k
    assert old_best_score == pytest.approx(partition.silhouette_score)

    # KMeans labels are arbitrary; order them by centroid before comparison.
    order = np.argsort(old_best_model.cluster_centers_.ravel())
    label_rank = np.empty(partition.k, dtype=np.intp)
    label_rank[order] = np.arange(partition.k)
    old_labels = label_rank[old_best_model.labels_].reshape(image.shape)
    assert np.array_equal(old_labels, partition.labels)

    print(
        f"exact weighted 1-D: k={partition.k}, "
        f"silhouette={partition.silhouette_score:.6f}, "
        f"thresholds={partition.thresholds.tolist()}, "
        f"time={exact_seconds:.4f}s"
    )
    print(
        f"seeded KMeans:      k={old_best_k}, "
        f"silhouette={old_best_score:.6f}, "
        f"time={kmeans_seconds:.4f}s"
    )


def test_adaptive_partition_40000_distinct_pixels_k10():
    """Report adaptive-histogram runtime for a high-cardinality image."""
    rng = np.random.default_rng(1729)
    intensities = np.concatenate([rng.normal(20 + 20 * group, 1.8, 4_000) for group in range(10)])
    image = intensities.reshape(200, 200)

    started = perf_counter()
    partition = xu.partition_intensities(image, n_clusters=10)
    elapsed = perf_counter() - started

    assert np.unique(image).size == 40_000
    assert partition.k == 10
    assert partition.thresholds.size == 9
    assert partition.labels.shape == image.shape
    assert partition.silhouette_score == pytest.approx(0.889673115914668)

    print(
        f"adaptive weighted 1-D, 40,000 pixels: k={partition.k}, "
        f"silhouette={partition.silhouette_score:.6f}, "
        f"time={elapsed:.4f}s"
    )


def test_log_transform_ignores_missing_pixels_and_handles_zero_maps():
    source = np.array([[0.0, 2.0, np.nan], [8.0, np.inf, 30.0]])
    finite = np.isfinite(source)
    with np.errstate(all="raise"):
        transformed = xu.log_transform(source)
        expected = xu.log_transform(source[finite])
        np.testing.assert_array_equal(xu.log_transform(np.zeros((3, 4))), 0)
    np.testing.assert_array_equal(transformed[finite], expected)
    assert np.isnan(transformed[~finite]).all()
    with pytest.raises(ValueError, match="no finite intensities"):
        xu.log_transform(np.full((2, 2), np.nan))


def test_missing_pixels_are_not_clustered_or_included_in_measurements():
    from exhale.xrf_refcopy.xrf_element_channel import ElementChannel

    source = np.arange(1.0, 401.0).reshape(20, 20)
    source[10, 10] = np.nan
    source[1, 2] = np.inf
    with np.errstate(invalid="raise"):
        channel = ElementChannel("P", source).process(min_k=2, max_k=3)
    assert np.isnan(channel.log_image[~np.isfinite(source)]).all()
    assert not channel.cluster_labels[~np.isfinite(source)].any()
    assert np.isfinite(channel.cluster_df["mean_intensity"]).all()
    assert channel.cluster_df["area"].sum() <= np.isfinite(source).sum()
