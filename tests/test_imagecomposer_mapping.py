"""Exact mapping from composed-image display pixels to source pixels."""

import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from qtpy import QtWidgets

from exhale.data.elementsettings import ElementSettings
from exhale.data.imagesettings import ImageSettings, Layouts, Scalebars
from exhale.data.source_refs import ElementRef
from exhale.imaging.imagecomposer import (
    ColoredRasterPrimitive,
    CompositionDescription,
    ImageComposer,
    RasterPrimitive,
    TextPrimitive,
    _nearest_lookup,
)


class NearestLookupTests(unittest.TestCase):
    def test_lookup_matches_pillow_for_up_and_downscaling(self):
        for source_size in range(1, 18):
            source = np.arange(source_size, dtype=np.int32).reshape(1, -1)
            for target_size in range(1, 23):
                with self.subTest(source=source_size, target=target_size):
                    resized = Image.fromarray(source, mode="I").resize(
                        (target_size, 1), Image.Resampling.NEAREST
                    )
                    np.testing.assert_array_equal(
                        _nearest_lookup(source_size, target_size), np.asarray(resized)[0]
                    )


class ComposedImageMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_image(self, layout):
        image = ImageSettings("mapping")
        image.layout = layout
        image.borderWidth = 3
        image.panelLabels = False
        image.elementLabels = False
        image.elementBorders = False
        image.scalebar = Scalebars.NONE
        for slot, shape in enumerate(((5, 7), (3, 11))):
            data = np.arange(np.prod(shape), dtype=float).reshape(shape)
            image.elements[slot] = ElementSettings(ElementRef(f"source-{slot}", "map"), data=data)
        return image

    def test_all_layouts_map_every_merged_display_pixel(self):
        for layout in Layouts:
            with self.subTest(layout=layout):
                composer = ImageComposer()
                output = composer.compose(self.make_image(layout))
                mapping = composer.coord_mapping
                self.assertLessEqual(mapping.x + mapping.width, output.shape[1])
                self.assertLessEqual(mapping.y + mapping.height, output.shape[0])
                for local_y in range(mapping.height):
                    for local_x in range(mapping.width):
                        self.assertEqual(
                            composer.map_coordinates(
                                mapping.x + local_x + 0.5, mapping.y + local_y + 0.5
                            ),
                            (int(mapping.source_x[local_x]), int(mapping.source_y[local_y])),
                        )

    def test_edges_use_half_open_pixel_rectangles(self):
        composer = ImageComposer()
        composer.compose(self.make_image(Layouts.IL))
        mapping = composer.coord_mapping
        self.assertEqual(
            composer.map_coordinates(mapping.x, mapping.y),
            (int(mapping.source_x[0]), int(mapping.source_y[0])),
        )
        self.assertEqual(
            composer.map_coordinates(
                mapping.x + mapping.width - 1e-9, mapping.y + mapping.height - 1e-9
            ),
            (int(mapping.source_x[-1]), int(mapping.source_y[-1])),
        )
        for x, y in (
            (mapping.x - 1e-9, mapping.y),
            (mapping.x, mapping.y - 1e-9),
            (mapping.x + mapping.width, mapping.y),
            (mapping.x, mapping.y + mapping.height),
        ):
            self.assertIsNone(composer.map_coordinates(x, y))

    def test_color_changes_reuse_transformed_element_layers(self):
        image = self.make_image(Layouts.IL)
        composer = ImageComposer()
        with ExitStack() as stack:
            transformed = [
                stack.enter_context(
                    patch.object(element, "transformedData", wraps=element.transformedData)
                )
                for element in image.elements.values()
            ]

            composer.compose(image)
            image.setColor(0, [0.8, 0.2, 0.1])
            composer.compose(image)

            self.assertTrue(all(method.call_count == 1 for method in transformed))

            image.elements[0].gamma += 0.1
            composer.compose(image)

            self.assertEqual(transformed[0].call_count, 2)
            self.assertTrue(all(method.call_count == 1 for method in transformed[1:]))

    def test_description_keeps_native_rasters_separate_from_layout(self):
        image = self.make_image(Layouts.IL)
        description = ImageComposer().describe(image)
        rasters = [
            primitive
            for primitive in description.primitives
            if isinstance(primitive, RasterPrimitive)
        ]

        self.assertIsInstance(description, CompositionDescription)
        self.assertEqual([raster.array.shape for raster in rasters[:2]], [(5, 7), (3, 11)])
        self.assertEqual(rasters[0].rect[2:], (7, 5))
        self.assertEqual(rasters[1].rect[2:], (11, 3))
        self.assertEqual(rasters[-1].array.shape, (5, 11, 3))
        self.assertEqual(
            rasters[-1].rect,
            (
                description.mapping.x,
                description.mapping.y,
                description.mapping.width,
                description.mapping.height,
            ),
        )

    def test_merged_only_layout_has_no_panel_letter(self):
        image = self.make_image(Layouts.MERGED)
        image.panelLabels = True

        description = ImageComposer().describe(image)

        self.assertFalse(
            any(isinstance(primitive, TextPrimitive) for primitive in description.primitives)
        )

    def test_additive_description_uses_native_scalar_layers(self):
        image = self.make_image(Layouts.IL)

        description = ImageComposer().describe(image, additive=True)
        layers = [
            primitive
            for primitive in description.primitives
            if isinstance(primitive, ColoredRasterPrimitive)
        ]

        self.assertEqual([layer.array.shape for layer in layers], [(5, 7), (3, 11)])
        self.assertTrue(all(layer.rect[:2] == layers[0].rect[:2] for layer in layers))
        self.assertEqual(layers[0].rect[:2], (description.mapping.x, description.mapping.y))
        self.assertEqual(layers[0].color, (1.0, 0.0, 0.0))
        self.assertEqual(layers[1].color, (0.0, 1.0, 0.0))

    def test_pdf_contains_separate_native_raster_panels(self):
        image = self.make_image(Layouts.IL)
        image.panelLabels = True
        image.elementLabels = True
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/composition.pdf"

            ImageComposer().compose(image, path)

            pdf = Path(path).read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreaterEqual(pdf.count(b"/Subtype /Image"), 3)


if __name__ == "__main__":
    unittest.main()
