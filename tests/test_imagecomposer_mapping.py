"""Exact mapping from composed-image display pixels to source pixels."""

import unittest

import numpy as np
from PIL import Image

from exhale.elementsettings import ElementSettings
from exhale.imagecomposer import ImageComposer, _nearest_lookup
from exhale.imagesettings import ImageSettings, Layouts, Scalebars
from exhale.source_refs import ElementRef


class NearestLookupTests(unittest.TestCase):
    def test_lookup_matches_pillow_for_up_and_downscaling(self):
        for source_size in range(1, 18):
            source = np.arange(source_size, dtype=np.int32).reshape(1, -1)
            for target_size in range(1, 23):
                with self.subTest(source=source_size, target=target_size):
                    resized = Image.fromarray(source, mode="I").resize(
                        (target_size, 1), Image.Resampling.NEAREST)
                    np.testing.assert_array_equal(
                        _nearest_lookup(source_size, target_size),
                        np.asarray(resized)[0])


class ComposedImageMappingTests(unittest.TestCase):
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
            image.elements[slot] = ElementSettings(
                ElementRef(f"source-{slot}", "map"), data=data)
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
                                mapping.x + local_x + 0.5,
                                mapping.y + local_y + 0.5),
                            (int(mapping.source_x[local_x]),
                             int(mapping.source_y[local_y])))

    def test_edges_use_half_open_pixel_rectangles(self):
        composer = ImageComposer()
        composer.compose(self.make_image(Layouts.IL))
        mapping = composer.coord_mapping
        self.assertEqual(
            composer.map_coordinates(mapping.x, mapping.y),
            (int(mapping.source_x[0]), int(mapping.source_y[0])))
        self.assertEqual(
            composer.map_coordinates(
                mapping.x + mapping.width - 1e-9,
                mapping.y + mapping.height - 1e-9),
            (int(mapping.source_x[-1]), int(mapping.source_y[-1])))
        for x, y in (
                (mapping.x - 1e-9, mapping.y),
                (mapping.x, mapping.y - 1e-9),
                (mapping.x + mapping.width, mapping.y),
                (mapping.x, mapping.y + mapping.height)):
            self.assertIsNone(composer.map_coordinates(x, y))


if __name__ == "__main__":
    unittest.main()
