#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Oct 12 22:38:36 2025
"""

import os
import numpy as np
from skimage import io, morphology
from magicgui import magic_factory, magicgui
from magicgui.widgets import Label
# import napari
from silx.gui import qt
from silx.gui.qt import Qt

def init_xrf_interface(parent, viewer):
    "Initialize a napari viewer"

    image_dict = {}
    labels_dict = {}
    df_full = None
    rootdir = "/tmp"
    print("xrf gui init")

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
    # tooltip.hide()

    # The main magicgui widget
    @magicgui(
        auto_call=True,
        sample={"choices": ["one", "two"]},
        element={"choices": ["aa", "bb"]},
        # sample={"choices": lambda w: list(image_dict.keys())},
        # element={"choices": lambda w: list(image_dict[next(iter(image_dict))].keys())}
    )
    def sample_selector(sample: str, element: str):
        sub_image_dict = image_dict[sample]
        sub_labels_dict = labels_dict[sample]
        nuclei_labels = sub_labels_dict['nuclei_labels']
        membrane_labels = sub_labels_dict['membrane_labels']

        df_results_nuclei = df_full[(df_full['samples']==sample)&(df_full['region']=='nuclei')]
        df_results_membrane = df_full[(df_full['samples']==sample)&(df_full['region']=='membrane')]

        # clear layers
        viewer.layers.clear()

        # load p_img if available
        path = os.path.join(rootdir, sample)
        for subdir, dirs, files in os.walk(path):
            for file in files:
                if "wP_" in file:
                    filename = os.path.join(subdir, file)
                    p_img = io.imread(filename)
                    viewer.add_image(p_img)

        # base layers
        img_shape = sub_image_dict['Ca']['log_image'].shape
        image_layer = viewer.add_image(np.zeros(img_shape), name="image")
        cluster_layer = viewer.add_image(np.zeros(img_shape), name="cluster")

        # labels
        labels_layer_nuclei = viewer.add_labels(morphology.erosion(nuclei_labels), name='Nuclei', opacity=0.5)
        labels_layer_membrane = viewer.add_labels(membrane_labels, name='Membrane', opacity=0.5)

        # update image on element selection
        def update_image(element_name):
            img_data = sub_image_dict[element_name]['log_image']
            cluster_data = sub_image_dict[element_name]['cluster']

            image_layer.data = img_data
            image_layer.name = element_name
            image_layer.contrast_limits = (np.min(img_data), np.max(img_data))

            cluster_layer.data = cluster_data
            cluster_layer.name = element_name + "_cluster"
            cluster_layer.contrast_limits = (np.min(cluster_data), np.min(cluster_data) + 1)
            cluster_layer.visible = False
            cluster_layer.opacity = 0.4
            cluster_layer.colormap = 'green'

        update_image(element)

        # tooltip callback
        def on_mouse_move(layer, event):
            pos = viewer.cursor.position
            if pos is None:
                tooltip.hide()
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
                tooltip.hide()
                return

            viewer.layers.selection.active = active_layer
            info_text = f"Label: {label_value}\n"

            if not info.empty:
                pos = viewer.window.qt_viewer.cursor().pos()
                tooltip.move(pos.x() + 20, pos.y() + 20)
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
                tooltip.setText(info_text)
                tooltip.adjustSize()
                tooltip.show()
            else:
                tooltip.hide()

        labels_layer_nuclei.mouse_move_callbacks.append(on_mouse_move)
        labels_layer_membrane.mouse_move_callbacks.append(on_mouse_move)

    ssel_gui = sample_selector
    print("Created GUI", ssel_gui)
    ssel_gui.insert(0, Label(value="This is magicgui\nand napari inside\na PyQt application"))

    # Add widget to viewer
    # Does not work with qtviewer (not using napari's main window)
    # viewer.window.add_dock_widget(ssel_gui, area="right")
    return ssel_gui

