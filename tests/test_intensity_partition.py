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
    intensities = np.concatenate((
        rng.normal(20, 2.0, 600),
        rng.normal(65, 4.0, 450),
        rng.normal(125, 3.0, 300),
    ))
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
            n_clusters=k, init="k-means++", max_iter=25, n_init=100,
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
