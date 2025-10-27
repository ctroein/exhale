#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Oct 12 22:38:36 2025
"""

import numpy as np
from skimage import morphology

import napari.viewer
from silx.gui import qt
from silx.gui.qt import Qt
from .xrf_main import process_xrf

class XrfViewer():
    def __init__(self, parent : qt.QWidget, viewer : napari.viewer.Viewer):
        self.image_dict = {}
        self.labels_dict = {}
        self.df_full = None
        self.viewer = viewer

        tooltip = qt.QLabel(parent)
        tooltip.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        tooltip.setAttribute(Qt.WA_ShowWithoutActivating)
        tooltip.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        tooltip.setStyleSheet("""
            background-color: white;
            border: 1px solid black;
            color: black;
            font-size: 12px;
            padding: 5px;
        """)
        tooltip.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
        tooltip.adjustSize()
        self.tooltip = tooltip
        # tooltip.hide()

    def run_analysis(self, path, data):
        # Q @ Tom: Are keys just different elements that are given special treatment?
        keys = None
        process_xrf(path, data, self.image_dict, keys)


    def sample_selector(self, sample: str, element: str, p_img : np.ndarray):
        sub_image_dict = self.image_dict[sample]
        sub_labels_dict = self.labels_dict[sample]
        nuclei_labels = sub_labels_dict['nuclei_labels']
        membrane_labels = sub_labels_dict['membrane_labels']

        df_full = self.df_full
        df_results_nuclei = df_full[(df_full['samples']==sample) &
                                    (df_full['region']=='nuclei')]
        df_results_membrane = df_full[(df_full['samples']==sample) &
                                      (df_full['region']=='membrane')]

        # clear layers
        self.viewer.layers.clear()
        self.viewer.add_image(p_img)

        # base layers
        img_shape = sub_image_dict['Ca']['log_image'].shape
        image_layer = self.viewer.add_image(np.zeros(img_shape), name="image")
        cluster_layer = self.viewer.add_image(np.zeros(img_shape), name="cluster")

        # labels
        labels_layer_nuclei = self.viewer.add_labels(
            morphology.erosion(nuclei_labels), name='Nuclei', opacity=0.5)
        labels_layer_membrane = self.viewer.add_labels(
            membrane_labels, name='Membrane', opacity=0.5)

        # update image on element selection
        def update_image(element_name):
            img_data = sub_image_dict[element_name]['log_image']
            cluster_data = sub_image_dict[element_name]['cluster']

            image_layer.data = img_data
            image_layer.name = element_name
            image_layer.contrast_limits = (np.min(img_data), np.max(img_data))

            cluster_layer.data = cluster_data
            cluster_layer.name = element_name + "_cluster"
            cluster_layer.contrast_limits = (
                np.min(cluster_data), np.min(cluster_data) + 1)
            cluster_layer.visible = False
            cluster_layer.opacity = 0.4
            cluster_layer.colormap = 'green'

        update_image(element)

        # tooltip callback
        def on_mouse_move(layer, event):
            pos = self.viewer.cursor.position
            if pos is None:
                self.tooltip.hide()
                return

            coords = tuple(int(round(c)) for c in pos)
            value_nuclei = labels_layer_nuclei.get_value(coords)
            value_membrane = labels_layer_membrane.get_value(coords)

            if value_nuclei != 0:
                active_layer = labels_layer_nuclei
                info = df_results_nuclei[df_results_nuclei['label'] == value_nuclei]
                label_value = value_nuclei
            elif value_membrane != 0:
                active_layer = labels_layer_membrane
                info = df_results_membrane[df_results_membrane['label'] == value_membrane]
                label_value = value_membrane
            else:
                self.tooltip.hide()
                return

            self.viewer.layers.selection.active = active_layer
            info_text = f"Label: {label_value}\n"

            if not info.empty:
                pos = self.viewer.window.qt_viewer.cursor().pos()
                self.tooltip.move(pos.x() + 20, pos.y() + 20)
                for item in sub_image_dict:
                    df_element = info[info['element'] == item]
                    if not df_element.empty:
                        sizes = ', '.join(map(str, df_element['cluster_sizes']))
                        intensities = ', '.join(map(str, df_element['cluster_intensities'].values[0]))
                        info_text += (
                            f"Element: {item}\n"
                            f"Avg intensity: {df_element['average_element_intensity'].values[0]}\n"
                            f"Clusters: {df_element['num_clusters'].values[0]}\n"
                            f"Size: {sizes}\n"
                            f"Intensity: {intensities}\n\n"
                        )
                self.tooltip.setText(info_text)
                self.tooltip.adjustSize()
                self.tooltip.show()
            else:
                self.tooltip.hide()

        labels_layer_nuclei.mouse_move_callbacks.append(on_mouse_move)
        labels_layer_membrane.mouse_move_callbacks.append(on_mouse_move)


