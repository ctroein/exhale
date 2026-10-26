#!/usr/bin/env python3
"""Embedded Napari viewer integration and analysis-layer presentation."""

from weakref import WeakKeyDictionary

import napari
import numpy as np
from napari.components import ViewerModel
from napari.layers import Image, Labels
from napari.utils.colormaps import Colormap
from napari.utils.colormaps.standardize_color import transform_color
from qtpy import QtGui, QtWidgets
from skimage import morphology


class NapariHelper:
    """Own the embedded Napari model, widget, and Exhale-created layers."""

    def __init__(self, theme="light", abundance_units="ng/mm²"):
        viewer_model = ViewerModel()
        viewer_model.theme = theme
        self.viewer = viewer_model
        self.abundance_units = abundance_units
        self._label_presentations = WeakKeyDictionary()
        self._image_colors = WeakKeyDictionary()
        self._label_color_rng = np.random.default_rng()
        self.qtwidget = napari.qt.QtViewer(viewer_model)
        # Napari leaves two pixels above and below its canvas. The embedded
        # viewer should align with the adjacent panes in Exhale.
        self.qtwidget.widget(0).layout().setContentsMargins(0, 0, 0, 0)
        self.set_theme(theme)
        self.sample = None
        self.nuc_layer = None
        self.mem_layer = None
        self._element_layers = {}
        self._fixed_layers = {}
        self._element_layer_pool = []
        self._cluster_layer_pool = []
        self.viewer.mouse_move_callbacks.append(self._hover)
        self.viewer.mouse_drag_callbacks.append(self._click)
        self.info_widget = None

    LABEL_CATEGORICAL = "categorical"
    LABEL_MASK = "mask"
    LABEL_MONOCHROME = "monochrome"
    LABEL_MODES = (LABEL_CATEGORICAL, LABEL_MASK, LABEL_MONOCHROME)
    MONOCHROME_LEVELS = (0.4, 0.6, 0.8, 1.0)
    BACKGROUND_ROLE = "background"
    TISSUE_RAW_ROLE = "tissue_raw"
    NUCLEI_RAW_ROLE = "nuclei_raw"
    GAIN_ROLES = (TISSUE_RAW_ROLE, NUCLEI_RAW_ROLE)
    GAIN_BASE_UPPER = "exhale_gain_base_upper"
    ACTIVE_KEY = "exhale_active"
    BLENDING_NORMAL = "translucent_no_depth"
    BLENDING_ADD = "additive"

    @staticmethod
    def _rgba(color):
        "Return one normalized RGBA color."
        return transform_color(color)[0]

    @classmethod
    def _label_color_dict(cls, layer, mode, color):
        rgba = cls._rgba(color)
        colors = {0: (0.0, 0.0, 0.0, 0.0), None: tuple(rgba)}
        labels = np.unique(layer.data)
        labels = labels[labels != layer.colormap.background_value]
        for label in labels:
            label = int(label)
            if mode == cls.LABEL_MONOCHROME:
                level = cls.MONOCHROME_LEVELS[(label - 1) % len(cls.MONOCHROME_LEVELS)]
                label_color = np.append(rgba[:3] * level, rgba[3])
            else:
                label_color = rgba
            colors[label] = tuple(label_color)
        return colors

    def _new_label_color(self):
        color = QtGui.QColor.fromHsvF(float(self._label_color_rng.random()), 1.0, 1.0, 1.0)
        return np.asarray(color.getRgbF())

    def _label_presentation(self, layer):
        presentation = self._label_presentations.get(layer)
        if presentation is None:
            presentation = {
                "categorical_colormaps": [layer.colormap],
                "palette_index": 0,
                "mode": self.LABEL_CATEGORICAL,
                "color": self._new_label_color(),
            }
            self._label_presentations[layer] = presentation
        return presentation

    def label_display_mode(self, layer):
        "Return the display mode and base color for a labels layer."
        if not isinstance(layer, Labels):
            raise TypeError("Label display modes apply only to Napari Labels layers")
        presentation = self._label_presentation(layer)
        return presentation["mode"], presentation["color"]

    def categorical_colors(self, layer, count=4):
        "Return representative colors from a labels layer's categorical palette."
        if not isinstance(layer, Labels):
            raise TypeError("Categorical colors apply only to Napari Labels layers")
        presentation = self._label_presentations.get(layer)
        colormap = (
            layer.colormap
            if presentation is None
            else presentation["categorical_colormaps"][presentation["palette_index"]]
        )
        return colormap.map(np.arange(1, count + 1))

    def reseed_label_colormap(self, layer):
        "Choose another permutation of Napari's categorical label colors."
        if not isinstance(layer, Labels):
            raise TypeError("Categorical colors apply only to Napari Labels layers")
        mode, color = self.label_display_mode(layer)
        if mode != self.LABEL_CATEGORICAL:
            raise ValueError("The categorical display mode must be active before reseeding")
        presentation = self._label_presentation(layer)
        if color is not None:
            presentation["color"] = color
        palette_index = (presentation["palette_index"] + 1) % 5
        if palette_index >= len(presentation["categorical_colormaps"]):
            layer.new_colormap(seed=palette_index)
            presentation["categorical_colormaps"].append(layer.colormap)
        else:
            layer.colormap = presentation["categorical_colormaps"][palette_index]
        presentation["palette_index"] = palette_index
        return layer.colormap

    def set_label_display(self, layer, mode, color=None):
        "Set categorical, single-color mask, or monochrome label display."
        if not isinstance(layer, Labels):
            raise TypeError("Label display modes apply only to Napari Labels layers")
        if mode not in self.LABEL_MODES:
            raise ValueError(f"Unknown label display mode: {mode!r}")

        presentation = self._label_presentation(layer)

        if color is not None:
            presentation["color"] = self._rgba(color)
        if mode == self.LABEL_CATEGORICAL:
            layer.colormap = presentation["categorical_colormaps"][presentation["palette_index"]]
        else:
            layer.colormap = self._label_color_dict(layer, mode, presentation["color"])
        presentation["mode"] = mode
        return layer.colormap

    def set_layer_opacity(self, layer, percent):
        "Set a layer opacity expressed as an integer percentage."
        if not 0 <= percent <= 100:
            raise ValueError("Layer opacity must be between 0 and 100 percent")
        layer.opacity = percent / 100

    def image_color(self, layer):
        "Return the selected monochrome color for an image layer."
        if not isinstance(layer, Image):
            raise TypeError("Image colors apply only to Napari Image layers")
        color = self._image_colors.get(layer)
        if color is not None:
            return color
        return np.asarray(layer.colormap.map([1.0])[0])

    def set_image_color(self, layer, color):
        "Display an image layer as a black-to-color monochrome scale."
        if not isinstance(layer, Image):
            raise TypeError("Image colors apply only to Napari Image layers")
        rgba = self._rgba(color)
        layer.colormap = Colormap(
            colors=((0.0, 0.0, 0.0, rgba[3]), tuple(rgba)),
            name="Exhale monochrome",
        )
        self._image_colors[layer] = rgba
        return layer.colormap

    @staticmethod
    def set_layer_blending(layer, blending):
        layer.blending = blending

    @classmethod
    def layer_has_gain(cls, layer):
        return layer.metadata.get("exhale_role") in cls.GAIN_ROLES

    @classmethod
    def layer_gain(cls, layer):
        if not cls.layer_has_gain(layer):
            raise TypeError("Gain applies only to the nuclei and tissue image layers")
        return layer.metadata[cls.GAIN_BASE_UPPER] / layer.contrast_limits[1]

    @classmethod
    def set_layer_gain(cls, layer, gain):
        if not cls.layer_has_gain(layer):
            raise TypeError("Gain applies only to the nuclei and tissue image layers")
        if not 1 <= gain <= 10:
            raise ValueError("Layer gain must be between 1 and 10")
        layer.contrast_limits = (0, layer.metadata[cls.GAIN_BASE_UPPER] / gain)

    @classmethod
    def is_background_layer(cls, layer):
        return layer.metadata.get("exhale_role") == cls.BACKGROUND_ROLE

    @classmethod
    def is_active_layer(cls, layer):
        """Return whether a pooled layer belongs to the displayed sample."""
        return layer.metadata.get(cls.ACTIVE_KEY, True)

    def user_layers(self):
        "Return the layers exposed in Exhale's layer controls."
        return tuple(
            layer
            for layer in self.viewer.layers
            if self.is_active_layer(layer) and not self.is_background_layer(layer)
        )

    def set_theme(self, theme):
        "Apply the viewer theme while retaining a predictable compositing background."
        if theme not in ("light", "dark"):
            raise ValueError(f"Unknown viewer theme: {theme!r}")
        from napari.utils.theme import get_theme

        self.viewer.theme = theme
        self.qtwidget.canvas.background_color_override = None
        self.qtwidget.canvas.bgcolor = get_theme(theme).canvas.as_hex()

    def move_layer(self, layer, target_index):
        "Move a layer to a final index in Napari's layer order."
        if self.is_background_layer(layer) or not self.is_active_layer(layer):
            return False
        active_layers = list(self.user_layers())
        if not 0 <= target_index < len(active_layers):
            raise IndexError("Layer index out of range")
        active_layers.remove(layer)
        active_layers.insert(target_index, layer)
        self._set_active_layer_order(active_layers)
        return True

    def set_info_widget(self, widget):
        self.info_widget = widget

    def _point(self, event):
        pos = event.position
        if len(pos) < 2:
            return None
        return tuple(map(int, pos[-2:]))

    def _build_tooltip_text(
        self, label_val: int, region_df, element_names: list[str], region_name: str
    ) -> str:
        rows = region_df[region_df["label"] == label_val]
        if rows.empty:
            return ""

        text = [f"{region_name}: {label_val}"]
        for elem in element_names:
            row = rows[rows["element"] == elem]
            if row.empty:
                continue
            r = row.iloc[0]
            # sizes = ", ".join(f"{v:.0f}" for v in r["cluster_sizes"])
            # intensities = ", ".join(f"{v:.3g}" for v in r["cluster_intensities"])
            text.append(
                f"{elem}: avg={r['average_element_intensity']:.3g} {self.abundance_units}, "
                f"number of overlapping clusters={r['num_clusters']}"
                # f"sizes=[{sizes}], intensities=[{intensities}]"
            )
        return "\n".join(text)

    @staticmethod
    def _cluster_row(ch, label):
        if ch.cluster_df is None or label <= 0:
            return None
        rows = ch.cluster_df[ch.cluster_df["label"] == label]
        return None if rows.empty else rows.iloc[0]

    def _cluster_tooltip_text(self, y, x):
        lines = []
        for name, ch in self.sample.elements.items():
            if ch.cluster_labels is None:
                continue
            if not (0 <= y < ch.cluster_labels.shape[0] and 0 <= x < ch.cluster_labels.shape[1]):
                continue
            label = int(ch.cluster_labels[y, x])
            row = self._cluster_row(ch, label)
            if row is None:
                continue
            lines.append(
                f"{name} ({row['area']:.0f} px, "
                f"avg {row['mean_intensity']:.4g} {self.abundance_units})"
            )
        return "" if not lines else "Clusters:\n" + "\n".join(lines)

    def _tt_hide(self):
        QtWidgets.QToolTip.hideText()

    def _tt_show(self, text):
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text, self.qtwidget)

    def _hover(self, obj, event):
        if self.sample is None:
            return self._tt_hide()
        sample = self.sample
        point = self._point(event)
        if point is None:
            return self._tt_hide()
        y, x = point
        nuclei = sample.nuclei.nuclei_labels
        membrane = sample.nuclei.membrane_labels
        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            return self._tt_hide()

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        text = None
        if self.nuc_layer.visible and nuc_label > 0:
            text = self._build_tooltip_text(
                nuc_label, sample.df_nuclei, sample.element_names, "Nucleus"
            )
        elif self.mem_layer.visible and mem_label > 0:
            text = self._build_tooltip_text(
                mem_label, sample.df_membrane, sample.element_names, "Membrane"
            )
        cluster_text = self._cluster_tooltip_text(y, x)
        if text and cluster_text:
            text += "\n\n" + cluster_text
        elif cluster_text:
            text = cluster_text

        if not text:
            return self._tt_hide()
        self._tt_show(text)

    def _click(self, obj, event):
        if event.type != "mouse_press" or event.button != 1:
            return
        if self.sample is None or self.info_widget is None:
            return

        point = self._point(event)
        if point is None:
            return
        y, x = point
        sample = self.sample
        nuclei = sample.nuclei.nuclei_labels
        membrane = sample.nuclei.membrane_labels
        self.info_widget.clear()

        if not (0 <= y < nuclei.shape[0] and 0 <= x < nuclei.shape[1]):
            return

        nuc_label = int(nuclei[y, x])
        mem_label = int(membrane[y, x])

        if nuc_label > 0:
            region_name = "Nucleus"
            region_label = nuc_label
            region_labels = nuclei
            region_df = sample.df_nuclei
        elif mem_label > 0:
            region_name = "Membrane"
            region_label = mem_label
            region_labels = membrane
            region_df = sample.df_membrane
        else:
            region_name = "Background"
            region_label = 0
            region_labels = None
            region_df = None

        lines = [
            f"Clicked coordinates: x={x}, y={y}",
            f"{region_name}: {region_label}",
        ]

        if region_labels is not None:
            region_mask = region_labels == region_label
            lines.append(f"{region_name} size: {int(region_mask.sum())} px")
        else:
            region_mask = None

        for elem, ch in sample.elements.items():
            lines.extend(["", elem])

            if 0 <= y < ch.raw.shape[0] and 0 <= x < ch.raw.shape[1]:
                lines.append(f"Point intensity: {ch.raw[y, x]:.4g} {self.abundance_units}")

            if region_df is not None:
                rows = region_df[
                    (region_df["label"] == region_label) & (region_df["element"] == elem)
                ]
                if not rows.empty:
                    r = rows.iloc[0]
                    lines.append(
                        f"Average intensity in {region_name.lower()}: "
                        f"{r['average_element_intensity']:.4g} "
                        f"{self.abundance_units}"
                    )

            if region_mask is not None and ch.cluster_labels is not None:
                cluster_ids = sorted(
                    int(v) for v in set(ch.cluster_labels[region_mask]) if int(v) > 0
                )
                if cluster_ids:
                    lines.append("Overlapping element clusters:")
                    for cid in cluster_ids:
                        row = self._cluster_row(ch, cid)
                        if row is None:
                            continue
                        overlap = int(((ch.cluster_labels == cid) & region_mask).sum())
                        lines.append(
                            f"  {cid}: size {row['area']:.0f} px, "
                            f"overlap {overlap} px, "
                            f"avg {row['mean_intensity']:.4g} "
                            f"{self.abundance_units}"
                        )

            if ch.cluster_labels is not None:
                cid = int(ch.cluster_labels[y, x])
                row = self._cluster_row(ch, cid)
                if row is not None:
                    lines.append("Element cluster at point:")
                    lines.append(
                        f"  {cid}: size {row['area']:.0f} px, "
                        f"avg {row['mean_intensity']:.4g} "
                        f"{self.abundance_units}"
                    )

        self.info_widget.setPlainText("\n".join(lines))

    def _ensure_layer_pools(self):
        """Initialize pool state for helpers constructed without ``__init__`` in tests."""
        if not hasattr(self, "_fixed_layers"):
            self._fixed_layers = {}
        if not hasattr(self, "_element_layer_pool"):
            self._element_layer_pool = []
        if not hasattr(self, "_cluster_layer_pool"):
            self._cluster_layer_pool = []

    def _set_layer_active(self, layer, active):
        layer.metadata[self.ACTIVE_KEY] = active
        if not active:
            layer.visible = False
            dtype = np.int32 if isinstance(layer, Labels) else np.float32
            layer.data = np.zeros((1, 1), dtype=dtype)

    def _fixed_image(self, role, data, *, name, visible, colormap):
        layer = self._fixed_layers.get(role)
        if layer is None:
            layer = self.viewer.add_image(
                data,
                name=name,
                visible=visible,
                colormap=colormap,
                blending=self.BLENDING_ADD,
                metadata={"exhale_role": role, self.ACTIVE_KEY: True},
            )
            layer.editable = False
            self._fixed_layers[role] = layer
        else:
            layer.data = data
            layer.name = name
            layer.visible = visible
            layer.opacity = 1.0
            layer.colormap = colormap
            layer.blending = self.BLENDING_ADD
            self._set_layer_active(layer, True)
        self._image_colors.pop(layer, None)
        return layer

    def _fixed_labels(self, role, data, *, name, visible, opacity=1.0):
        layer = self._fixed_layers.get(role)
        if layer is None:
            layer = self.viewer.add_labels(
                data,
                name=name,
                visible=visible,
                opacity=opacity,
                blending=self.BLENDING_NORMAL,
                metadata={"exhale_role": role, self.ACTIVE_KEY: True},
            )
            self._fixed_layers[role] = layer
        else:
            layer.data = data
            layer.name = name
            layer.visible = visible
            layer.opacity = opacity
            layer.blending = self.BLENDING_NORMAL
            layer.new_colormap(seed=0)
            self._set_layer_active(layer, True)
        self._label_presentations.pop(layer, None)
        return layer

    def _pooled_element_layer(self, index, name, data):
        if index == len(self._element_layer_pool):
            layer = self.viewer.add_image(
                data,
                name=f"{name} map",
                visible=False,
                colormap="red",
                blending=self.BLENDING_ADD,
                metadata={
                    "exhale_role": "element_map",
                    "exhale_element": name,
                    self.ACTIVE_KEY: True,
                },
            )
            self._element_layer_pool.append(layer)
        else:
            layer = self._element_layer_pool[index]
            layer.data = data
            layer.name = f"{name} map"
            layer.visible = False
            layer.opacity = 1.0
            layer.colormap = "red"
            layer.blending = self.BLENDING_ADD
            layer.metadata["exhale_element"] = name
            self._set_layer_active(layer, True)
        self._image_colors.pop(layer, None)
        return layer

    def _pooled_cluster_layer(self, index, name, data):
        if index == len(self._cluster_layer_pool):
            layer = self.viewer.add_labels(
                data,
                name=f"{name} clusters",
                visible=False,
                blending=self.BLENDING_NORMAL,
                metadata={
                    "exhale_role": "element_clusters",
                    "exhale_element": name,
                    self.ACTIVE_KEY: True,
                },
            )
            self._cluster_layer_pool.append(layer)
        else:
            layer = self._cluster_layer_pool[index]
            layer.data = data
            layer.name = f"{name} clusters"
            layer.visible = False
            layer.opacity = 1.0
            layer.blending = self.BLENDING_NORMAL
            layer.new_colormap(seed=index + 1)
            layer.metadata["exhale_element"] = name
            self._set_layer_active(layer, True)
        self._label_presentations.pop(layer, None)
        return layer

    def _deactivate_unused_layers(self, element_count, cluster_count):
        for layer in self._element_layer_pool[element_count:]:
            self._set_layer_active(layer, False)
        for layer in self._cluster_layer_pool[cluster_count:]:
            self._set_layer_active(layer, False)

    def _set_active_layer_order(self, active_layers):
        """Place active layers above the backing layer in their compositing order."""
        backgrounds = [layer for layer in self.viewer.layers if self.is_background_layer(layer)]
        inactive = [
            layer
            for layer in self.viewer.layers
            if not self.is_background_layer(layer) and not self.is_active_layer(layer)
        ]
        desired = backgrounds + inactive + list(active_layers)
        layers = self.viewer.layers
        for target, layer in enumerate(desired):
            source = layers.index(layer)
            if source == target:
                continue
            destination = target + 1 if target > source else target
            layers.move(source, destination)

    def set_sample(self, sample, element_maps=None):
        "Set/update the XRFSample using reusable fixed and variable layer pools."
        self._ensure_layer_pools()
        self.sample = sample
        if sample is None:
            for layer in self.viewer.layers:
                self._set_layer_active(layer, False)
            self.nuc_layer = None
            self.mem_layer = None
            self._element_layers = {}
            return

        element_items = tuple(sample.elements.items())
        if element_maps is None:
            element_maps = tuple(channel.raw for _name, channel in element_items)
        else:
            element_maps = tuple(element_maps)
            if len(element_maps) != len(element_items):
                raise ValueError("Displayed element maps must match the segmentation elements")

        self._element_layers = {}

        self._fixed_image(
            self.BACKGROUND_ROLE,
            np.zeros(sample.tissue.raw.shape, dtype=np.uint8),
            name="Background",
            visible=True,
            colormap=Colormap(colors=("black", "black"), name="Exhale black backing"),
        )
        tissue_layer = self._fixed_image(
            self.TISSUE_RAW_ROLE,
            sample.tissue.raw,
            name="Tissue raw",
            visible=False,
            colormap="blue",
        )
        tissue_layer.reset_contrast_limits()
        tissue_layer.metadata[self.GAIN_BASE_UPPER] = tissue_layer.contrast_limits[1]
        nuclei_layer = self._fixed_image(
            self.NUCLEI_RAW_ROLE,
            sample.nuclei.raw,
            name="Nuclei raw",
            visible=True,
            colormap="green",
        )
        nuclei_layer.reset_contrast_limits()
        nuclei_layer.metadata[self.GAIN_BASE_UPPER] = nuclei_layer.contrast_limits[1]

        cluster_layers = []
        element_layers = []
        for index, ((name, ch), display_map) in enumerate(
            zip(element_items, element_maps, strict=True)
        ):
            layer = self._pooled_element_layer(index, name, display_map)
            self._element_layers[name] = layer
            element_layers.append(layer)
            if ch.cluster_labels is not None:
                cluster_layers.append((name, ch.cluster_labels))

        active_cluster_layers = [
            self._pooled_cluster_layer(index, name, labels)
            for index, (name, labels) in enumerate(cluster_layers)
        ]

        self.mem_layer = self._fixed_labels(
            "membrane_labels",
            sample.nuclei.membrane_labels,
            name="Membrane labels",
            visible=False,
        )
        self.nuc_layer = self._fixed_labels(
            "nuclei_labels",
            morphology.erosion(sample.nuclei.nuclei_labels),
            name="Nuclei labels",
            visible=True,
            opacity=0.6,
        )
        self._deactivate_unused_layers(len(element_layers), len(active_cluster_layers))
        self._set_active_layer_order(
            (
                tissue_layer,
                nuclei_layer,
                *element_layers,
                *active_cluster_layers,
                self.mem_layer,
                self.nuc_layer,
            )
        )
        self.viewer.reset_view(margin=0)
        # attach_napari_hover(sample, viewer, widget, nuc_layer, mem_layer)

    def update_element_maps(self, maps):
        """Replace data for existing element-map layers without rebuilding the viewer."""
        unknown = set(maps) - set(self._element_layers)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise KeyError(f"No element-map layer for: {names}")
        for name, data in maps.items():
            self._element_layers[name].data = data
