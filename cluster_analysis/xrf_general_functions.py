# from stardist.models import StarDist2D
from csbdeep.utils import normalize
# import tensorflow as tf

# import os
# from skimage import measure, io
from skimage.segmentation import expand_labels
import numpy as np
import pandas as pd

# os.environ["CUDA_VISIBLE_DEVICES"] = "0"
# print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))
# model = StarDist2D(None, '2D_versatile_fluo_copy', basedir='.')

def log_img(img):
    # Logarithmic transformation inspired by Fiji's "log" function
    # Scale factor ensures result is normalized in [0,255]
    c = 255 / np.log1p(img.max())
    log_image = c * np.log1p(img.astype(np.float32))
    # Subtract mean, clip negatives to zero, and cast back to original dtype
    element_img = np.clip(log_image - log_image.mean(), 0, None).astype(img.dtype)
    return element_img

def draw_filtered_img(labels, df):
    # Create a boolean mask where label IDs are in the filtered dataframe
    mask = np.isin(labels, df['label'])
    # Initialize empty mask with same shape as labels
    filtered_image = np.zeros_like(labels)
    filtered_image[mask] = labels[mask]
    return filtered_image

def build_segmented_image(img_shape, mask):
    """Create binary image of segmented clusters."""
    segmented_img = np.zeros(img_shape, dtype=np.uint8)
    segmented_img[mask] = 1
    return segmented_img

def segment_nuclei(img_nuclei, model):
    # Run deep learning segmentation model on nuclei channel
    labels, _ = model.predict_instances(normalize(img_nuclei))
    return labels

def create_membrane_nuclei(labels_nuclei, expansion_size = 15, return_expanded = True):
    # Expand nuclei labels by a fixed distance
    expanded_labels = expand_labels(labels_nuclei, distance=expansion_size)
    membrane_labels = expanded_labels - labels_nuclei
    if return_expanded:
        return expanded_labels, membrane_labels
    else:
        return membrane_labels

def flatten_df(df, location):
    # Flatten per-cell lists of cluster sizes and intensities into long format
    flat_cluster_sizes = [item for sublist in df['cluster_sizes'] for item in sublist]
    flat_cluster_intensities = [item for sublist in df['cluster_intensities'] for item in sublist]
    elements = [df['element'][i] for i in range(len(df)) for _ in df['cluster_sizes'][i]]

    # Construct normalized (flattened) dataframe
    df_flat = pd.DataFrame({
        'element': elements,
        'cluster_size': flat_cluster_sizes,
        'cluster_intensity': flat_cluster_intensities,
        'location': location
    })
    return df_flat