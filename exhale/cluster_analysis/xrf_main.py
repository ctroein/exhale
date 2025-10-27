import os
from skimage import measure, io
# from skimage.segmentation import expand_labels
# import numpy as np
import pandas as pd
import importlib

from . import xrf_clustering as xc
from . import xrf_general_functions as xgf

model = None

def init_model():
    global model
    from stardist.models import StarDist2D
    # from csbdeep.utils import normalize
    import tensorflow as tf

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))
    model = StarDist2D(None, "2D_versatile_fluo_copy",
                       basedir=importlib.resources.files("exhale.resources"))


def process_xrf(path, img, image_dict, keys):

    # Determine which channel/key this file belongs to
    matching_key = next((x for x in keys if x in path), None)
    if matching_key is None:
        return image_dict

    clean_key = matching_key.replace('w', '').replace('_', '')
    image_dict.setdefault(clean_key, {})

    if model is None:
        init_model()

    if matching_key == 'wP_':
        #normalized_image = exposure.rescale_intensity(img, in_range=(0, 255), out_range=(0, 1))
        #img = util.img_as_uint(normalized_image)
        nuclei = img - img.min()
        labels = xgf.segment_nuclei(nuclei, model)

        # Extract cell properties
        df_nuclei = pd.DataFrame(
            measure.regionprops_table(
                label_image=labels,
                intensity_image=img,
                properties=('label', 'area', 'mean_intensity')
            )
        )

        # filter nuclei
        intensity_thresh = img.mean() + img.std()
        df_nuclei_filtered = df_nuclei[
            (df_nuclei['mean_intensity'] > intensity_thresh) &
            (df_nuclei['area'] > 100)
        ]
        nuclei_filtered = xgf.draw_filtered_img(df_nuclei_filtered, labels)

        #Label expansion
        expanded_labels, membrane_labels = xgf.create_membrane_nuclei(nuclei_filtered)

        # store results
        image_dict[clean_key].update({
            'nuclei_labels': nuclei_filtered,
            'expanded_labels': expanded_labels,
            'membrane_labels': membrane_labels
        })

    elif matching_key == 'wCl_': # tissue channel
        tissue_img = xgf.log_img(img)
        tissue_threshold = tissue_img > 0
        image_dict[clean_key].update({
            'tissue_initial': img,
            'tissue_threshold': tissue_threshold
        })

    else: # element channels
        element_img = xgf.log_img(img)
        # Estimate number of clusters automatically
        nb_cluster = xc.measure_number_cluster(element_img)
        # Perform clustering + extract per-cluster statistics
        clustered_image, cluster_df = xc.measure_clusters_properties_v2(element_img, nb_cluster, img)
        image_dict[clean_key].update({
            'raw_data': img,
            'log_image': element_img,
            'cluster': clustered_image,
            'dataframe': cluster_df
        })

    return image_dict

def compute_tissue_properties(tissue_labels, element_raw_data):
    """Compute tissue area and mean intensity for clusters > 20 px."""
    tissue_table = pd.DataFrame(measure.regionprops_table(
        tissue_labels,
        element_raw_data,
        properties=['area', 'mean_intensity']
    ))
    tissue_area_table = tissue_table[tissue_table['area'] > 20]
    return tissue_area_table['area'].sum(), tissue_area_table['mean_intensity'].mean()

def process_region(labels, element_img, element_key, temp_df, region_name, df_results):
    """Process clusters within a given labeled region (nuclei or membrane)."""
    for region in measure.regionprops(labels, element_img):
        min_row, min_col, max_row, max_col = region.bbox

        # Find overlapping clusters
        region_clusters = temp_df[
            (min_row < temp_df['centroid-0']) & (temp_df['centroid-0'] < max_row) &
            (min_col < temp_df['centroid-1']) & (temp_df['centroid-1'] < max_col)
        ]

        num_clusters = region_clusters.shape[0]
        cluster_sizes = region_clusters['area'].values if num_clusters else []
        cluster_intensities = region_clusters['mean_intensity'].values if num_clusters else []

        df_results.append({
            'label': region.label,
            'element': element_key,
            'region': region_name,
            'num_clusters': num_clusters,
            'cluster_sizes': cluster_sizes,
            'cluster_intensities': cluster_intensities,
            'average_element_intensity': region.intensity_mean
        })

        # Remove processed clusters
        temp_df.drop(region_clusters.index, inplace=True)

    return temp_df

def process_background(temp_df, element_key, tissue_mean_intensity, df_results):
    """Process leftover clusters as non-cellular background."""
    num_clusters = temp_df.shape[0]
    cluster_sizes = temp_df['area'].values if num_clusters else []
    cluster_intensities = temp_df['mean_intensity'].values if num_clusters else []

    df_results.append({
        'label': 1000, # dummy label for background
        'element': element_key,
        'region': 'non_cellular',
        'num_clusters': num_clusters,
        'cluster_sizes': cluster_sizes,
        'cluster_intensities': cluster_intensities,
        'average_element_intensity': tissue_mean_intensity
    })

def combine_results(image_dict, sample):
    """Combine nuclei, membrane, and background results into unified dataframes."""
    df_nuclei, df_membrane, df_background = [], [], []

    # Pop nuclei and tissue channels from dict
    nuclei_image_dict = image_dict.pop('P', None)
    tissue_image_dict = image_dict.pop('Cl', None)

    labels_nuclei = nuclei_image_dict['nuclei_labels']
    labels_membrane = nuclei_image_dict['membrane_labels']
    labels_background = nuclei_image_dict['expanded_labels']

    tissue_threshold = tissue_image_dict['tissue_threshold']
    tissue_labels = measure.label(tissue_threshold, connectivity=2)

    # Iterate over elements
    for key, image in image_dict.items():
        element_raw_data = image['raw_data']
        element_img = image['log_image']
        temp_df = image['dataframe'].copy()

        # Tissue properties
        tissue_area, tissue_mean_intensity = compute_tissue_properties(tissue_labels, element_raw_data)

        # Process regions
        temp_df = process_region(labels_nuclei, element_img, key, temp_df, 'nuclei', df_nuclei)
        temp_df = process_region(labels_membrane, element_img, key, temp_df, 'membrane', df_membrane)

        # Background
        process_background(temp_df, key, tissue_mean_intensity, df_background)

    # Convert to DataFrames
    df_nuclei = pd.DataFrame(df_nuclei)
    df_membrane = pd.DataFrame(df_membrane)
    df_background = pd.DataFrame(df_background)

    # Flatten
    df_flat_nuclei = xgf.flatten_df(df_nuclei, 'nuclei')
    df_flat_membrane = xgf.flatten_df(df_membrane, 'membrane')
    df_flat_non_cellular = xgf.flatten_df(df_background, 'non_cellular')

    # Merge
    df_results = pd.concat([df_flat_nuclei, df_flat_membrane, df_flat_non_cellular])
    df_results['samples'] = sample
    df_results['tissue_area'] = tissue_area

    # Add sample column to raw dfs
    for df in (df_nuclei, df_membrane, df_background):
        df['samples'] = sample

    return df_results, df_nuclei, df_membrane, df_background, nuclei_image_dict

def combine_results_legacy(image_dict, sample):
    # Initialize a list to store the results
    df_nuclei = []
    df_membrane = []
    df_background = []
    nuclei_image_dict = image_dict.pop('P', None)
    tissue_image_dict = image_dict.pop('Cl', None)
    #c = np.exp(-5)

    labels_nuclei = nuclei_image_dict['nuclei_labels']
    labels_membrane = nuclei_image_dict['membrane_labels']
    # labels_background = nuclei_image_dict['expanded_labels']

    tissue_threshold = tissue_image_dict['tissue_threshold']
    tissue_labels = measure.label(tissue_threshold, connectivity=2)

    # Iterate over each element in the image dictionary
    for key, image in image_dict.items():
        element_raw_data = image['raw_data']
        element_img = image['log_image']
        temp = image['dataframe'].copy()

        tissue_props = measure.regionprops_table(tissue_labels, element_raw_data, properties=['area', 'mean_intensity'])
        tissue_table = pd.DataFrame(tissue_props)
        tissue_area_table = tissue_table[tissue_table['area']>20]#.sum()
        tissue_area = tissue_area_table['area'].sum()
        tissue_mean_intensity = tissue_area_table['mean_intensity'].mean()

        # Process nuclei
        for nucleus in measure.regionprops(labels_nuclei, element_img):
            # Get the bounding box of the nucleus
            min_row, min_col, max_row, max_col = nucleus.bbox

            temp_nuclei = temp[(min_row<temp['centroid-0']) & (temp['centroid-0']<max_row) & (min_col<temp['centroid-1']) &(temp['centroid-1']<max_col)]
            num_clusters = temp_nuclei.shape[0]
            if num_clusters == 0:
                cluster_sizes = []
                cluster_intensities = []
            else:
                cluster_sizes = temp_nuclei['area'].values
                cluster_intensities = temp_nuclei['mean_intensity'].values
            # Store the results for the current nucleus
            df_nuclei.append({
                'label': nucleus.label,
                'element': key,
                'region': 'nuclei',
                'num_clusters': num_clusters,
                'cluster_sizes': cluster_sizes,
                'cluster_intensities': cluster_intensities,
                'average_element_intensity': nucleus.intensity_mean
            })
            byebyerows = temp_nuclei.index
            temp = temp.drop(byebyerows, axis=0)

        # Process membrane
        for nucleus in measure.regionprops(labels_membrane, element_img):
            # Get the bounding box of the membrane
            min_row, min_col, max_row, max_col = nucleus.bbox

            temp_membrane = temp[(min_row<temp['centroid-0']) & (temp['centroid-0']<max_row) & (min_col<temp['centroid-1']) & (temp['centroid-1']<max_col)]
            num_clusters = temp_membrane.shape[0]
            if num_clusters == 0:
                cluster_sizes = []
                cluster_intensities = []
            else:
                cluster_sizes = temp_membrane['area'].values
                cluster_intensities = temp_membrane['mean_intensity'].values
            # Store the results for the current nucleus
            df_membrane.append({
                'label': nucleus.label,
                'element': key,
                'region': 'membrane',
                'num_clusters': num_clusters,
                'cluster_sizes': cluster_sizes,
                'cluster_intensities': cluster_intensities,
                'average_element_intensity': nucleus.intensity_mean
            })
            byebyerows = temp_membrane.index
            temp = temp.drop(byebyerows, axis=0)

        # Process background
        # Extract the cluster labels within the background
        # Create a background mask (True for background, False for nuclei)

        num_clusters = temp.shape[0]
        if num_clusters == 0:
            cluster_sizes = []
            cluster_intensities = []
        else:
            cluster_sizes = temp['area'].values
            cluster_intensities = temp['mean_intensity'].values
        df_background.append({
                'label': 1000,
                'element': key,
                'region': 'non_cellular',
                'num_clusters': num_clusters,
                'cluster_sizes': cluster_sizes,
                'cluster_intensities': cluster_intensities,
                'average_element_intensity': tissue_mean_intensity
            })

    df_nuclei = pd.DataFrame(df_nuclei)
    df_membrane = pd.DataFrame(df_membrane)
    df_background = pd.DataFrame(df_background)

    df_flat_nuclei = xgf.flatten_df(df_nuclei, 'nuclei')
    df_flat_membrane = xgf.flatten_df(df_membrane, 'membrane')
    df_flat_non_cellular = xgf.flatten_df(df_background, 'non_cellular')

    df_results = pd.concat([df_flat_nuclei, df_flat_membrane, df_flat_non_cellular])
    df_results['samples'] = sample
    df_results['tissue_area'] = tissue_area
    #df_results['tissue_intensity'] = tissue_mean_intensity

    df_nuclei['samples'] = sample
    df_membrane['samples'] = sample
    df_background['samples'] = sample
    return df_results, df_nuclei, df_membrane, df_background, nuclei_image_dict

