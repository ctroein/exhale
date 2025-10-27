from skimage import measure
from sklearn.cluster import KMeans
import numpy as np
import pandas as pd

# import dask.array as da
# from dask.diagnostics import ProgressBar
# import dask.dataframe as dd
# import tensorflow as tf

from sklearn.metrics import silhouette_score
# from sklearn.cluster import KMeans
from collections import Counter
import dask
from dask import delayed

from . import xrf_general_functions as xgf

@delayed
def run_clustering(X, min_k=3, max_k=5, n_init=1):
    best_k, best_score = None, -1
    for k in range(min_k, max_k+1):
        labels = KMeans(n_clusters=k, init='k-means++', max_iter=100, n_init=n_init).fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_k, best_score = k, score
    return best_k

def measure_number_cluster_legacy(image, num_runs = 100):
    # Assuming element_img is defined somewhere in your code

    # Number of times to run the experiment


    # Create a list of delayed tasks
    tasks = [run_clustering(image) for _ in range(num_runs)]

    # Compute the results in parallel
    best_clusters_list = dask.compute(*tasks)

    # Determine the most frequent number of clusters
    most_frequent_clusters = Counter(best_clusters_list).most_common(1)[0][0]
    #print("The most frequent best number of clusters is %i" % most_frequent_clusters)
    return most_frequent_clusters

def measure_number_cluster(X, min_k=3, max_k=5, n_init=100):
    """Find best number of clusters in [min_k, max_k] using silhouette score."""
    best_score, best_k = -1, min_k
    for n_clusters in range(min_k, max_k + 1):
        model = KMeans(n_clusters=n_clusters, init='k-means++', max_iter=100, n_init=n_init)
        labels = model.fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_score, best_k = score, n_clusters
    return best_k

def run_kmeans(img, num_clusters):
    """Run KMeans clustering on the flattened image."""
    kmeans = KMeans(n_clusters=num_clusters, init="k-means++")
    flat_img = img.reshape(-1, 1)
    kmeans.fit(flat_img)
    return kmeans.labels_.reshape(img.shape)

def extract_cluster_positions(labels, max_cluster_size=10000):
    """Extract pixel positions for clusters below size threshold."""
    cluster_positions = {}
    cluster_sizes = np.bincount(labels.ravel())

    for label, size in enumerate(cluster_sizes):
        if size <= max_cluster_size:
            coords = np.column_stack(np.where(labels == label))
            cluster_positions[label] = coords

    return cluster_positions

def build_mask(img_shape, cluster_positions):
    """Build boolean mask of all cluster positions."""
    if not cluster_positions:
        return np.zeros(img_shape, dtype=bool)

    all_points = np.vstack(list(cluster_positions.values()))
    mask = np.zeros(img_shape, dtype=bool)
    mask[tuple(all_points.T)] = True
    return mask

def compute_cluster_properties(segmented_img, raw_img, min_area=1):
    """Compute cluster properties and filter by area."""
    labels = measure.label(segmented_img, connectivity=2)
    props = measure.regionprops_table(
        labels,
        raw_img,
        properties=["label", "area", "mean_intensity", "centroid"]
    )
    df = pd.DataFrame(props)
    filtered_df = df[df["area"] > min_area]
    return labels, filtered_df

def measure_clusters_properties(img, num_clusters, raw_img, max_cluster_size=10000):
    """Main pipeline: KMeans clustering + property extraction + filtering."""
    # Step 1: Run clustering
    k_labels = run_kmeans(img, num_clusters)

    # Step 2: Extract cluster positions
    cluster_positions = extract_cluster_positions(k_labels, max_cluster_size=max_cluster_size)

    # Step 3: Build mask and segmented image
    mask = build_mask(img.shape, cluster_positions)
    segmented_img = xgf.build_segmented_image(img.shape, mask)

    # Step 4: Compute cluster properties
    labels, filtered_df = compute_cluster_properties(segmented_img, raw_img)

    # Step 5: Filter image by properties
    filtered_image = xgf.draw_filtered_img(labels, filtered_df)

    return filtered_image, filtered_df


#def measure_clusters_properties_v2(img, num_clusters, raw_img):
    # Apply K-Means clustering
    kmeans = KMeans(n_clusters=num_clusters, init='k-means++')
    kmeans.fit(img.reshape(-1, 1))
    # Extract cluster positions and calculate intensity and size
    cluster_positions = {}

    # Define a maximum size threshold for clusters
    max_cluster_size = 10000  # Adjust this threshold as needed
    # Get cluster labels
    k_labels = kmeans.labels_
    # cluster_sizes = np.bincount(k_labels)
    for label in set(k_labels):
        cluster_indices = np.where(k_labels == label)[0]
        cluster_size = len(cluster_indices)

        if cluster_size <= max_cluster_size:
            # Collect cluster points
            cluster_coords = np.unravel_index(cluster_indices, img.shape)
            cluster_positions[label] = np.column_stack(cluster_coords)


    # Prepare data for Napari
    points_list = []
    for cluster_id, positions in cluster_positions.items():
        points_list.append(positions)

    # If there are points to display, concatenate them into a single array
    if points_list:
        all_points = np.vstack(points_list)
    else:
        all_points = np.empty((0, 2))

    # Create a mask for the segmented points
    mask = np.zeros_like(img, dtype=bool)
    for point in all_points:
        mask[tuple(point)] = True

    # Overlay the mask on the original image
    segmented_img = np.zeros_like(img) #element_img.copy()
    segmented_img[mask] = 1 #element_img[mask]#.max()  # Highlight segmented pixels

    k_space_labels = measure.label(segmented_img, connectivity=2)
    k_props = measure.regionprops_table(k_space_labels, raw_img, properties=['label', 'area', 'mean_intensity', 'centroid'])
    k_df = pd.DataFrame(k_props)
    filtered_k_df = k_df[(k_df['area']>1) ] #& (k_df['mean_intensity']>(np.exp(element_img)+c).mean())
    mask = np.isin(k_space_labels, filtered_k_df)
    filtered_image = np.zeros_like(k_space_labels)
    filtered_image[mask] = k_space_labels[mask]

    return filtered_image, filtered_k_df