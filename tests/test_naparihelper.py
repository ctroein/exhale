import unittest
from types import SimpleNamespace
from weakref import WeakKeyDictionary

import napari
import numpy as np
from napari.components import ViewerModel
from napari.layers import Image, Labels
from napari.utils.colormaps import Colormap
from qtpy import QtCore, QtWidgets

from exhale.analysis.naparihelper import NapariHelper


class NapariPresentationTest(unittest.TestCase):
    def setUp(self):
        self.helper = NapariHelper.__new__(NapariHelper)
        self.helper.viewer = ViewerModel()
        self.helper._label_presentations = WeakKeyDictionary()
        self.helper._image_colors = WeakKeyDictionary()
        self.helper._label_color_rng = np.random.default_rng(0)
        self.labels = self.helper.viewer.add_labels(
            np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint8), name="Labels"
        )

    def test_mask_and_categorical_modes(self):
        original_colormap = self.labels.colormap

        self.helper.set_label_display(self.labels, self.helper.LABEL_MASK, "#4080c0")

        self.assertIsNone(self.labels.get_color(0))
        expected = (64 / 255, 128 / 255, 192 / 255, 1)
        np.testing.assert_allclose(self.labels.get_color(1), expected)
        np.testing.assert_allclose(self.labels.get_color(5), self.labels.get_color(1))
        mode, color = self.helper.label_display_mode(self.labels)
        self.assertEqual(mode, self.helper.LABEL_MASK)
        np.testing.assert_allclose(color, expected)

        self.helper.set_label_display(self.labels, self.helper.LABEL_CATEGORICAL)

        self.assertIs(self.labels.colormap, original_colormap)
        self.assertEqual(
            self.helper.label_display_mode(self.labels)[0], self.helper.LABEL_CATEGORICAL
        )

    def test_non_categorical_label_modes_start_with_a_full_brightness_color(self):
        mode, color = self.helper.label_display_mode(self.labels)

        self.assertEqual(mode, self.helper.LABEL_CATEGORICAL)
        self.assertAlmostEqual(color[:3].max(), 1)
        self.assertAlmostEqual(color[:3].min(), 0)

        other = self.helper.viewer.add_labels(
            np.array([[0, 1]], dtype=np.uint8), name="Other labels"
        )
        other_color = self.helper.label_display_mode(other)[1]
        self.assertFalse(np.allclose(color, other_color))

    def test_monochrome_mode_uses_four_stable_brightness_levels(self):
        self.helper.set_label_display(self.labels, self.helper.LABEL_MONOCHROME, "red")

        for label, brightness in enumerate((0.4, 0.6, 0.8, 1.0), start=1):
            np.testing.assert_allclose(self.labels.get_color(label), (brightness, 0, 0, 1))
        np.testing.assert_allclose(self.labels.get_color(5), self.labels.get_color(1))

    def test_categorical_palette_can_be_reseeded(self):
        original_colormap = self.labels.colormap

        self.helper.reseed_label_colormap(self.labels)

        self.assertIsNot(self.labels.colormap, original_colormap)
        self.assertEqual(
            self.helper.label_display_mode(self.labels)[0], self.helper.LABEL_CATEGORICAL
        )
        np.testing.assert_allclose(
            self.helper.categorical_colors(self.labels),
            self.labels.colormap.map(np.arange(1, 5)),
        )

        for _index in range(4):
            self.helper.reseed_label_colormap(self.labels)
        self.assertIs(self.labels.colormap, original_colormap)

    def test_layer_presentation_and_reordering(self):
        first = self.helper.viewer.add_image(np.zeros((2, 2)), name="First")
        second = self.helper.viewer.add_image(np.ones((2, 2)), name="Second")

        self.helper.set_image_color(first, "#804020")
        self.helper.set_layer_opacity(first, 30)
        self.helper.set_layer_blending(first, "additive")
        self.helper.move_layer(first, 2)

        self.assertEqual(first.opacity, 0.3)
        self.assertEqual(first.blending, "additive")
        np.testing.assert_allclose(
            self.helper.image_color(first), (128 / 255, 64 / 255, 32 / 255, 1)
        )
        self.assertEqual(list(self.helper.viewer.layers), [self.labels, second, first])

        self.helper.move_layer(first, 0)
        self.assertEqual(list(self.helper.viewer.layers), [first, self.labels, second])

    def test_background_is_limited_to_a_fixed_bottom_layer(self):
        self.helper.viewer = ViewerModel()
        background = self.helper.viewer.add_image(
            np.zeros((2, 2), dtype=np.uint8),
            metadata={"exhale_role": self.helper.BACKGROUND_ROLE},
        )
        foreground = self.helper.viewer.add_image(np.ones((2, 2)))

        self.assertFalse(self.helper.move_layer(background, 1))
        self.helper.move_layer(foreground, 0)
        self.assertEqual(list(self.helper.viewer.layers), [background, foreground])

    def test_sample_layers_use_fixed_black_backing_and_type_defaults(self):
        self.helper.viewer = ViewerModel()
        raw = np.ones((3, 4), dtype=np.float32)
        sample = SimpleNamespace(
            tissue=SimpleNamespace(raw=raw),
            nuclei=SimpleNamespace(
                raw=raw,
                membrane_labels=np.zeros_like(raw, dtype=np.uint8),
                nuclei_labels=np.ones_like(raw, dtype=np.uint8),
            ),
            elements={
                "Fe": SimpleNamespace(raw=raw, cluster_labels=np.ones_like(raw, dtype=np.uint8))
            },
        )

        display_map = np.full(raw.shape, 0.25, dtype=np.float32)
        self.helper.set_sample(sample, (display_map,))

        layers = list(self.helper.viewer.layers)
        self.assertTrue(self.helper.is_background_layer(layers[0]))
        self.assertEqual(layers[0].blending, self.helper.BLENDING_ADD)
        np.testing.assert_allclose(
            layers[0].colormap.map([0, 1]), np.array([[0, 0, 0, 1], [0, 0, 0, 1]])
        )
        self.assertEqual(layers[0].data.shape, raw.shape)
        image_layers = [layer for layer in layers[1:] if isinstance(layer, Image)]
        label_layers = [layer for layer in layers[1:] if isinstance(layer, Labels)]
        self.assertTrue(image_layers)
        self.assertTrue(label_layers)
        self.assertTrue(all(layer.blending == self.helper.BLENDING_ADD for layer in image_layers))
        self.assertTrue(
            all(layer.blending == self.helper.BLENDING_NORMAL for layer in label_layers)
        )
        tissue_layer = next(layer for layer in image_layers if layer.name == "Tissue raw")
        nuclei_layer = next(layer for layer in image_layers if layer.name == "Nuclei raw")
        element_layer = next(layer for layer in image_layers if layer.name == "Fe map")
        np.testing.assert_allclose(tissue_layer.colormap.map([1])[0, :3], (0, 0, 1))
        np.testing.assert_allclose(element_layer.colormap.map([1])[0, :3], (1, 0, 0))
        np.testing.assert_array_equal(element_layer.data, display_map)
        self.assertEqual(self.helper.layer_gain(tissue_layer), 1)
        initial_upper = nuclei_layer.contrast_limits[1]
        self.helper.set_layer_gain(nuclei_layer, 2.4)
        self.assertAlmostEqual(nuclei_layer.contrast_limits[1], initial_upper / 2.4)
        self.assertAlmostEqual(self.helper.layer_gain(nuclei_layer), 2.4)
        self.assertGreater(layers.index(label_layers[0]), layers.index(element_layer))
        self.assertNotIn(layers[0], self.helper.user_layers())
        self.assertEqual(self.helper.user_layers(), tuple(layers[1:]))

    def test_displayed_element_map_count_must_match_segmentation_elements(self):
        self.helper.viewer = ViewerModel()
        raw = np.ones((2, 2), dtype=np.float32)
        sample = SimpleNamespace(
            tissue=SimpleNamespace(raw=raw),
            nuclei=SimpleNamespace(
                raw=raw,
                membrane_labels=np.zeros_like(raw, dtype=np.uint8),
                nuclei_labels=np.ones_like(raw, dtype=np.uint8),
            ),
            elements={"Fe": SimpleNamespace(raw=raw, cluster_labels=None)},
        )

        with self.assertRaisesRegex(ValueError, "must match"):
            self.helper.set_sample(sample, ())

    def test_element_map_update_retains_layers_and_presentation(self):
        self.helper.viewer = ViewerModel()
        raw = np.ones((2, 3), dtype=np.float32)
        sample = SimpleNamespace(
            tissue=SimpleNamespace(raw=raw),
            nuclei=SimpleNamespace(
                raw=raw,
                membrane_labels=np.zeros_like(raw, dtype=np.uint8),
                nuclei_labels=np.ones_like(raw, dtype=np.uint8),
            ),
            elements={"Fe": SimpleNamespace(raw=raw, cluster_labels=None)},
        )
        self.helper.set_sample(sample, (raw,))
        layers = tuple(self.helper.viewer.layers)
        element_layer = next(layer for layer in layers if layer.name == "Fe map")
        element_layer.visible = True
        element_layer.opacity = 0.35

        replacement = np.full(raw.shape, 0.25, dtype=np.float32)
        self.helper.update_element_maps({"Fe": replacement})

        self.assertEqual(tuple(self.helper.viewer.layers), layers)
        self.assertIs(
            next(layer for layer in self.helper.viewer.layers if layer.name == "Fe map"),
            element_layer,
        )
        np.testing.assert_array_equal(element_layer.data, replacement)
        self.assertTrue(element_layer.visible)
        self.assertEqual(element_layer.opacity, 0.35)


class NapariRenderingTest(unittest.TestCase):
    def test_normal_layers_render_in_order_and_respect_opacity(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        viewer = napari.Viewer(show=False)
        viewer.window._qt_window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
        viewer.window._qt_window.show()
        viewer.window.resize(400, 400)
        shape = (64, 64)

        def colormap(name, color):
            return Colormap(colors=((0, 0, 0, 1), color), name=name)

        viewer.add_image(
            np.zeros(shape),
            name="Backing",
            colormap=colormap("black", (0, 0, 0, 1)),
            contrast_limits=(0, 1),
            blending=NapariHelper.BLENDING_ADD,
        )
        for name, color, opacity in (
            ("R", (1, 0, 0, 1), 1.0),
            ("G", (0, 1, 0, 1), 1.0),
            ("B", (0, 0, 1, 1), 0.0),
        ):
            viewer.add_image(
                np.ones(shape),
                name=name,
                colormap=colormap(name, color),
                contrast_limits=(0, 1),
                opacity=opacity,
                blending=NapariHelper.BLENDING_NORMAL,
            )
        viewer.reset_view()
        app.processEvents()

        try:
            screenshot = viewer.screenshot(size=(400, 400), canvas_only=True, flash=False)
            np.testing.assert_allclose(screenshot[..., :3].max(axis=(0, 1)), (0, 255, 0), atol=1)

            viewer.layers["B"].opacity = 0.5
            app.processEvents()
            screenshot = viewer.screenshot(size=(400, 400), canvas_only=True, flash=False)
            np.testing.assert_allclose(screenshot[..., :3].max(axis=(0, 1)), (0, 127, 128), atol=1)
        finally:
            viewer.close()


if __name__ == "__main__":
    unittest.main()
