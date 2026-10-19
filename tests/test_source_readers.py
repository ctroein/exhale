"""Storage-independent element loading and reader resource ownership."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import tifffile

from exhale.data.source_refs import ElementRef, open_source


class SourceReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = np.arange(12).reshape(3, 4)

    def open(self, path):
        source = open_source(path)
        self.addCleanup(source.close)
        return source

    def test_tiff_preserves_dtype_values_and_orientation(self):
        for dtype in (np.uint8, np.uint16, np.int16, np.float32, np.float64):
            with self.subTest(dtype=dtype):
                path = self.root / (np.dtype(dtype).name + ".tif")
                data = self.data.astype(dtype)
                if data.dtype.kind == "f":
                    data = data / 3 - 2
                    data[0, 0] = np.nan
                tifffile.imwrite(path, data, photometric="minisblack")
                source = self.open(path)
                (candidate,) = source.list_elements()
                self.assertEqual(candidate.ref.item_id, "page/0")
                result = source.load_array(candidate.ref)
                self.assertEqual(result.dtype, data.dtype)
                np.testing.assert_array_equal(result, data)

    def test_multipage_bigtiff_and_deflate(self):
        path = self.root / "stack.tif"
        with tifffile.TiffWriter(path, bigtiff=True) as writer:
            for data in (self.data.astype("uint16"), self.data.astype("float32") / 3):
                writer.write(data, photometric="minisblack", compression="deflate")
        source = self.open(path)
        candidates = source.list_elements()
        self.assertEqual([c.ref.item_id for c in candidates], ["page/0", "page/1"])
        self.assertEqual([c.name for c in candidates], ["stack [page 1]", "stack [page 2]"])
        np.testing.assert_array_equal(source.load_array(candidates[0].ref), self.data)
        np.testing.assert_array_equal(
            source.load_array(candidates[1].ref), self.data.astype("float32") / 3
        )

    def test_ome_channel_names_are_exposed_as_channel_keys(self):
        path = self.root / "named-channels.ome.tif"
        data = np.stack((self.data, self.data + 20, self.data + 40)).astype("float32")
        names = ["Al_K", "Fe_K", "Zn_K"]
        tifffile.imwrite(
            path,
            data,
            ome=True,
            photometric="minisblack",
            metadata={"axes": "CYX", "Channel": {"Name": names}},
        )

        source = self.open(path)
        candidates = source.list_elements()

        self.assertEqual([candidate.name for candidate in candidates], names)
        self.assertEqual([candidate.key for candidate in candidates], names)
        for index, candidate in enumerate(candidates):
            np.testing.assert_array_equal(source.load_array(candidate.ref), data[index])

    def test_invalid_refs_and_closed_sources(self):
        path = self.root / "map.tif"
        tifffile.imwrite(path, self.data.astype("uint16"))
        source = self.open(path)
        ref = source.list_elements()[0].ref
        with self.assertRaises(ValueError):
            source.load_array(ElementRef("another-file", ref.item_id))
        for item in ("image", "page/-1", "page/01", "page/1", "page/a", "page/0/x"):
            with self.subTest(item=item), self.assertRaises(ValueError):
                source.load_array(ElementRef(source.source_id, item))
        data = source.load_array(ref)
        handle = source.handle
        source.close()
        source.close()
        self.assertTrue(handle.filehandle.closed)
        self.assertEqual(source.list_elements(), [])
        with self.assertRaises(RuntimeError):
            source.load_array(ref)
        np.testing.assert_array_equal(data, self.data)

    def test_rgba_tiff_exposes_components_as_separate_maps(self):
        path = self.root / "rgb.tif"
        data = np.stack([self.data + offset for offset in (0, 20, 40, 60)], axis=-1).astype("uint8")
        tifffile.imwrite(path, data, photometric="rgb")

        source = self.open(path)
        candidates = source.list_elements()

        self.assertEqual(
            [candidate.ref.item_id for candidate in candidates],
            [f"page/0/component/{index}" for index in range(4)],
        )
        self.assertEqual(
            [candidate.name for candidate in candidates], ["Red", "Green", "Blue", "Alpha"]
        )
        for index, candidate in enumerate(candidates):
            self.assertEqual(source.channel_data(candidate.ref).shape, self.data.shape)
            np.testing.assert_array_equal(source.load_array(candidate.ref), data[..., index])

    def test_hdf5_default_and_subgroups(self):
        path = self.root / "map.data"  # detect content, not extension
        with h5py.File(path, "w") as f:
            f.attrs["default"] = np.bytes_("entry")
            group = f.create_group("entry/plotselect")
            group.create_dataset("Fe", data=self.data)
            group.create_group("metadata")
        source = self.open(path)
        (candidate,) = source.list_elements()
        self.assertEqual(candidate.ref.item_id, "/entry/plotselect/Fe")
        np.testing.assert_array_equal(source.load_array(candidate.ref), self.data)
        handle = source.handle
        source.close()
        self.assertFalse(handle.id.valid)

    def test_channel_data_exposes_backing_and_disposable_cache(self):
        path = self.root / "cached.h5"
        with h5py.File(path, "w") as f:
            f.attrs["default"] = "entry"
            f.create_dataset("entry/plotselect/Fe", data=self.data)
        source = self.open(path)
        ref = source.list_elements()[0].ref
        channel_data = source.channel_data(ref)

        self.assertIsInstance(channel_data.backing, h5py.Dataset)
        self.assertEqual(channel_data.shape, self.data.shape)
        self.assertEqual(channel_data.dtype, self.data.dtype)
        self.assertFalse(channel_data.has_cache)
        np.testing.assert_array_equal(channel_data.array(), self.data)
        self.assertTrue(channel_data.has_cache)

        source.close()
        self.assertTrue(channel_data.is_available)
        np.testing.assert_array_equal(channel_data.array(), self.data)
        channel_data.release_cache()
        self.assertFalse(channel_data.is_available)
        with self.assertRaisesRegex(RuntimeError, "Source is closed"):
            channel_data.array()

    def test_invalid_hdf5_layout_closes_reader(self):
        path = self.root / "invalid.h5"
        with h5py.File(path, "w"):
            pass
        reader = h5py.File(path, "r")
        with patch("exhale.data.source_refs.h5py.File", return_value=reader):
            with self.assertRaisesRegex(ValueError, "plotselect"):
                open_source(path)
        self.assertFalse(reader.id.valid)

    def test_non_map_hdf5_dataset_is_rejected(self):
        path = self.root / "scalar.h5"
        with h5py.File(path, "w") as f:
            f.attrs["default"] = "entry"
            f.create_dataset("entry/plotselect/scalar", data=1)
        source = self.open(path)
        with self.assertRaisesRegex(ValueError, "2-D"):
            source.load_array(source.list_elements()[0].ref)

    def test_unsupported_file(self):
        path = self.root / "invalid.txt"
        path.write_text("not an image")
        with self.assertRaises(tifffile.TiffFileError):
            open_source(path)
