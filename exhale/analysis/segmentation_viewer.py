"""Segmentation-only Napari presentation of a source map and instance labels."""

import numpy as np
from napari.utils.colormaps import Colormap
from skimage.measure import find_contours

from ..data.constants import CONCENTRATION_UNITS
from ..data.projectdata import LayerPresentation, SegmentationLayerSettings, SegmentationResult
from .naparihelper import NapariHelper


class SegmentationViewer(NapariHelper):
    """Reuse layer presentation controls without the clustering/XRF data model."""

    def __init__(self, theme="light", abundance_units=CONCENTRATION_UNITS):
        self.result = None
        self.input_map = None
        self.inspection_callback = None
        self.selection_callback = None
        self.rectangle_selection_callback = None
        self.edit_session = None
        self.edit_callback = None
        self.edit_tool = "select"
        self.brush_size = 5
        self._cancel_stroke = False
        self._stroke_active = False
        self._stroke_points = []
        self._selection_layers = []
        super().__init__(theme, abundance_units)
        self.viewer.mouse_drag_callbacks.append(self._edit_drag)
        from .segmentationcursor import SegmentationCursor

        self._editing_cursor = SegmentationCursor(self)
        getattr(self.viewer, "scene", self.viewer).camera.events.zoom.connect(self._selection_zoom)

    def user_layers(self):
        """Exclude selection decorations from user-controlled layer presentation."""
        return tuple(
            layer
            for layer in super().user_layers()
            if not layer.metadata.get("exhale_selection_overlay")
        )

    def set_result(
        self,
        result: SegmentationResult | None,
        input_map=None,
        reference_maps=(),
        *,
        fit=True,
        comparisons=(),
        edit_session=None,
    ) -> None:
        """Show the exact returned labels, retaining pooled layers between results.

        A missing source map does not prevent viewing saved segmentation labels.
        Layer settings are applied by the controller after replacing the data.
        """
        if result is not None and input_map is not None:
            if np.shape(input_map) != result.output.labels.shape:
                raise ValueError("The source map and segmentation labels have different shapes")
        self.result = result
        self.edit_session = edit_session
        self.set_edit_tool(getattr(self, "edit_tool", "select"))
        self.input_map = input_map
        self._ensure_layer_pools()
        comparisons = tuple(comparisons)
        comparison_ids = {candidate.candidate_id for candidate, _name in comparisons}
        for layer in tuple(self.viewer.layers):
            if "exhale_comparison_id" in layer.metadata:
                if layer.metadata["exhale_comparison_id"] not in comparison_ids:
                    self._fixed_layers.pop(layer.metadata["exhale_role"], None)
                    self.viewer.layers.remove(layer)
                else:
                    self._set_layer_active(layer, False)
        if result is None and input_map is None:
            for layer in self.viewer.layers:
                if layer.metadata.get("exhale_selection_overlay"):
                    layer.data = []
                    layer.visible = False
                    layer.editable = False
                    layer.metadata[self.ACTIVE_KEY] = False
                else:
                    self._set_layer_active(layer, False)
            self.nuc_layer = None
            return

        labels = (
            None
            if result is None
            else (result.processed_labels if edit_session is None else edit_session.labels)
        )

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
            labels,
            name="Nuclei labels",
            visible=True,
            opacity=0.6,
        )
        if self.nuc_layer is not None:
            self.nuc_layer.editable = False
        comparison_layers = []
        for candidate, name in comparisons:
            identity = f"comparison:{candidate.candidate_id}"
            layer = self._fixed_labels(
                identity,
                candidate.result.processed_labels,
                name=name,
                visible=True,
                opacity=0.6,
            )
            layer.editable = False
            if candidate.comparison_presentation is None:
                color = self.automatic_layer_color(exclude=layer, include_labels=True)
                candidate.comparison_presentation = LayerPresentation(
                    visible=True,
                    opacity=0.6,
                    blending=self.BLENDING_NORMAL,
                    color=color.getRgbF(),
                    label_mode=self.LABEL_MONOCHROME,
                    palette_index=0,
                )
            layer.metadata["exhale_comparison_id"] = candidate.candidate_id
            layer.metadata[self.LAYER_ID_KEY] = identity
            # Let subsequent new masks see this layer's saved color and visibility.
            self.apply_layer_settings(
                SegmentationLayerSettings(layers={identity: candidate.comparison_presentation})
            )
            comparison_layers.append(layer)
        self._set_active_layer_order(
            (source_layer, *reference_layers, *comparison_layers, self.nuc_layer)
        )
        settings = SegmentationLayerSettings(
            layers={
                f"comparison:{candidate.candidate_id}": candidate.comparison_presentation
                for candidate, _name in comparisons
                if candidate.comparison_presentation is not None
            }
        )
        self.apply_layer_settings(settings)
        self.update_selection()
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.refresh()
        if fit:
            self.viewer.reset_view(margin=0)

    def update_selection(self):
        """Draw contrasting outlines without changing label colors or saved arrays."""
        paths = []
        if self.edit_session is not None:
            for identity in sorted(self.edit_session.selected_ids):
                paths.extend(
                    contour - 1
                    for contour in find_contours(
                        np.pad(self.edit_session.labels == identity, 1), 0.5
                    )
                    if len(contour) >= 3
                )
        if paths and not self._selection_layers:
            for color in ("black", "white"):
                layer = self.viewer.add_shapes(
                    ndim=2,
                    shape_type="path",
                    name="Selection outline",
                    face_color="transparent",
                    edge_color=color,
                    blending=self.BLENDING_NORMAL,
                    metadata={"exhale_selection_overlay": True, self.ACTIVE_KEY: True},
                )
                layer.editable = False
                self._selection_layers.append(layer)
        for layer, color in zip(self._selection_layers, ("black", "white"), strict=False):
            layer.data = []
            if paths:
                layer.add_paths(paths, edge_color=color, face_color="transparent")
            layer.metadata[self.ACTIVE_KEY] = bool(paths)
            layer.visible = bool(paths)
            layer.editable = False
        self._selection_zoom()
        if paths:
            self._set_active_layer_order((*self.user_layers(), *self._selection_layers))

    def _selection_zoom(self, event=None):
        zoom = getattr(self.viewer, "scene", self.viewer).camera.zoom
        for layer, width in zip(self._selection_layers, (3, 1), strict=False):
            layer.edge_width = width / zoom

    def set_edit_tool(self, tool):
        """Reserve left drags for drawing while keeping wheel zoom available."""
        self.edit_tool = tool
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.cancel_selection()
        camera = getattr(self.viewer, "scene", self.viewer).camera
        camera.mouse_pan = self.edit_session is None or tool == "select"
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.refresh()

    def effective_edit_tool(self, inverted=False):
        """Resolve right-button inversion without changing the selected tool."""
        if inverted and self.edit_tool in ("add", "remove"):
            return "remove" if self.edit_tool == "add" else "add"
        return self.edit_tool

    def set_brush_size(self, size):
        """Update the transient footprint without changing labels or project state."""
        self.brush_size = size
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.refresh()

    def cancel_stroke(self):
        """Discard the uncommitted preview, leaving labels and undo history untouched."""
        self._cancel_stroke = True
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.cancel_selection()
        self._stroke_points = []
        if hasattr(self, "_editing_cursor"):
            self._editing_cursor.refresh()
        if self.edit_session is not None and self.nuc_layer is not None:
            self.nuc_layer.data = self.edit_session.labels

    def _edit_drag(self, obj, event):
        if (
            self.edit_session is None
            or self.edit_tool == "select"
            or (
                event.button != 1
                and not (event.button == 2 and self.edit_tool in ("add", "remove"))
            )
            or self.edit_callback is None
        ):
            return
        session = self.edit_session
        tool = self.edit_tool
        inverted = event.button == 2
        if tool == "draw":
            modifiers = {
                getattr(key, "name", str(key)).lower() for key in getattr(event, "modifiers", ())
            }
            if modifiers & {"control", "ctrl"}:
                tool = "outline_remove"
            elif "shift" in modifiers:
                tool = "outline_add"
        self._cancel_stroke = False
        self._stroke_active = True
        points = []
        strokes = []
        brush = tool in ("add", "remove")
        self._stroke_points = points

        def preview_point():
            coordinates = self.nuc_layer.world_to_data(event.position)[-2:]
            if not np.isfinite(coordinates).all():
                return
            point = tuple(map(float, coordinates))
            operation = self.effective_edit_tool(inverted)
            changed_tool = brush and (not strokes or strokes[-1][0] != operation)
            if not points or point != points[-1] or changed_tool:
                if changed_tool:
                    strokes.append((operation, [points[-1]] if points else []))
                if brush:
                    strokes[-1][1].append(point)
                points.append(point)
                if hasattr(self, "_editing_cursor"):
                    self._editing_cursor.refresh()
                labels = self.edit_callback(
                    "brush" if brush else tool, strokes if brush else points, preview=True
                )
                if labels is not None:
                    self.nuc_layer.data = labels

        try:
            preview_point()
            yield
            while event.type == "mouse_move":
                if self._cancel_stroke or self.edit_session is not session:
                    return
                preview_point()
                yield
            if not self._cancel_stroke and self.edit_session is session:
                preview_point()
                if points:
                    self.edit_callback("brush" if brush else tool, strokes if brush else points)
        finally:
            self._stroke_active = False
            self._stroke_points = []
            if hasattr(self, "_editing_cursor"):
                self._editing_cursor.refresh()
            if self.edit_session is session:
                self.nuc_layer.data = session.labels
                self.update_selection()

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
        labels = self.nuc_layer.data
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
        if self.edit_session is not None and getattr(self, "edit_tool", "select") != "select":
            return
        if event.type != "mouse_press" or event.button != 1 or self.info_widget is None:
            return
        self.info_widget.clear()
        point = self._label_at(event)
        if point is None:
            return
        y, x, label = point
        if self.edit_session is not None and self.selection_callback is not None:
            toggle = any(
                getattr(key, "name", str(key)).lower() in ("control", "ctrl")
                for key in getattr(event, "modifiers", ())
            )
            if self.selection_callback(label, toggle, position=(y, x)) is False:
                return
            y, x, label = self._label_at(event)
        lines = [f"Clicked coordinates: x={x}, y={y}"]
        if label:
            ids, areas = (
                self.result.segment_areas if self.edit_session is None else self.edit_session.areas
            )
            area = areas[np.searchsorted(ids, label)]
            lines.extend((f"Nucleus: {label}", f"Nucleus size: {area} px"))
        else:
            lines.append("Background: 0")
        self.info_widget.setPlainText("\n".join(lines))
        if self.inspection_callback is not None:
            self.inspection_callback()
