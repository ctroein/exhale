"""Segmentation-only Napari presentation of a source map and instance labels."""

import numpy as np
from napari.utils.colormaps import Colormap

from ..data.constants import CONCENTRATION_UNITS
from ..data.projectdata import SegmentationResult
from .naparihelper import NapariHelper


class SegmentationViewer(NapariHelper):
    """Reuse layer presentation controls without the clustering/XRF data model."""

    def __init__(self, theme="light", abundance_units=CONCENTRATION_UNITS):
        self.result = None
        self.input_map = None
        self.inspection_callback = None
        super().__init__(theme, abundance_units)

    def set_result(
        self, result: SegmentationResult | None, input_map=None, reference_maps=(), *, fit=True
    ) -> None:
        """Show the exact returned labels, retaining pooled layers between results.

        A missing source map does not prevent viewing saved segmentation labels.
        Layer settings are applied by the controller after replacing the data.
        """
        if result is not None and input_map is not None:
            if np.shape(input_map) != result.output.labels.shape:
                raise ValueError("The source map and segmentation labels have different shapes")
        self.result = result
        self.input_map = input_map
        self._ensure_layer_pools()
        if result is None and input_map is None:
            for layer in self.viewer.layers:
                self._set_layer_active(layer, False)
            self.nuc_layer = None
            return

        shape = result.processed_labels.shape if result is not None else np.shape(input_map)
        self._fixed_image(
            self.BACKGROUND_ROLE,
            np.zeros(shape, dtype=np.uint8),
            name="Background",
            visible=True,
            colormap=Colormap(colors=("black", "black"), name="Exhale black backing"),
        )
        source_layer = self._fixed_image(
            self.NUCLEI_RAW_ROLE, input_map, name="Nuclei raw", visible=True, colormap="green"
        )
        if source_layer is not None:
            source_layer.reset_contrast_limits()
            source_layer.metadata[self.GAIN_BASE_UPPER] = source_layer.contrast_limits[1]
        reference_layers = []
        for ref, name, data in reference_maps:
            if np.shape(data) != shape:
                continue
            layer = self._pooled_element_layer(len(reference_layers), name, str(ref), data)
            layer.metadata["exhale_reference_ref"] = ref
            layer.visible = True
            reference_layers.append(layer)
        self._deactivate_unused_layers(len(reference_layers), 0)
        self.nuc_layer = self._fixed_labels(
            "nuclei_labels",
            None if result is None else result.processed_labels,
            name="Nuclei labels",
            visible=True,
            opacity=0.6,
        )
        if self.nuc_layer is not None:
            self.nuc_layer.editable = False
        self._set_active_layer_order((source_layer, *reference_layers, self.nuc_layer))
        if fit:
            self.viewer.reset_view(margin=0)

    def update_reference_maps(self, maps):
        """Refresh transformed reference data without resetting presentation or camera."""
        by_ref = {ref: data for ref, _name, data in maps}
        for layer in self.user_layers():
            ref = layer.metadata.get("exhale_reference_ref")
            if ref in by_ref and np.shape(by_ref[ref]) == layer.data.shape:
                layer.data = by_ref[ref]

    def _label_at(self, event):
        """Return the source-image coordinates and instance ID under the pointer."""
        if self.result is None:
            return None
        # Match Napari's nearest-pixel lookup, including transformed coordinates.
        coordinates = self.nuc_layer.world_to_data(event.position)[-2:]
        if len(coordinates) != 2 or not np.isfinite(coordinates).all():
            return None
        y, x = np.round(coordinates).astype(int)
        labels = self.result.processed_labels
        if not (0 <= y < labels.shape[0] and 0 <= x < labels.shape[1]):
            return None
        return y, x, int(labels[y, x])

    def _hover(self, obj, event):
        point = self._label_at(event)
        if point is None or self.nuc_layer is None or not self.nuc_layer.visible or point[2] == 0:
            self._tt_hide()
            return
        self._tt_show(f"Nucleus: {point[2]}")

    def _click(self, obj, event):
        if event.type != "mouse_press" or event.button != 1 or self.info_widget is None:
            return
        self.info_widget.clear()
        point = self._label_at(event)
        if point is None:
            return
        y, x, label = point
        lines = [f"Clicked coordinates: x={x}, y={y}"]
        if label:
            ids, areas = self.result.segment_areas
            area = areas[np.searchsorted(ids, label)]
            lines.extend((f"Nucleus: {label}", f"Nucleus size: {area} px"))
        else:
            lines.append("Background: 0")
        self.info_widget.setPlainText("\n".join(lines))
        if self.inspection_callback is not None:
            self.inspection_callback()
