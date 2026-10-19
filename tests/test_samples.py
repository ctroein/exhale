"""Data-sample construction, TIFF editing, and compatibility checks."""

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np
import tifffile

from exhale.data.projectdata import ProjectData
from exhale.data.source_refs import open_source
from exhale.data.tiffimport import infer_tiff_import


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = []

    def tearDown(self):
        for source in self.sources:
            source.close()

    def open(self, path):
        source = open_source(path)
        self.sources.append(source)
        return source

    def make_tiff(self, name, shape=(3, 4)):
        path = self.root / name
        tifffile.imwrite(path, np.arange(np.prod(shape), dtype=np.uint16).reshape(shape))
        return path

    def test_hdf5_source_creates_one_sample_with_all_channels(self):
        path = self.root / "scan.h5"
        with h5py.File(path, "w") as handle:
            handle.attrs["default"] = "entry"
            group = handle.create_group("entry/plotselect")
            group.create_dataset("Fe", data=np.ones((3, 4)))
            group.create_dataset("Zn", data=np.ones((3, 4)))
        project = ProjectData()

        sample = project.register_source(self.open(path))
        project.rename_sample(sample.sample_id, "Experiment 1")

        self.assertEqual(sample.name, "Experiment 1")
        self.assertEqual(sample.shape, (3, 4))
        self.assertEqual(set(sample.channels), {"Fe", "Zn"})
        self.assertEqual(sample.asset_ids, [str(path)])
        self.assertEqual(project.assets[str(path)].sample_id, sample.sample_id)

    def test_ome_channel_names_become_sample_channel_keys(self):
        path = self.root / "stack.ome.tif"
        data = np.stack((np.ones((3, 4)), np.full((3, 4), 2))).astype("float32")
        tifffile.imwrite(
            path,
            data,
            ome=True,
            photometric="minisblack",
            metadata={"axes": "CYX", "Channel": {"Name": ["Fe_K", "Zn_K"]}},
        )
        project = ProjectData()

        sample = project.register_source(self.open(path))

        self.assertEqual(set(sample.channels), {"Fe_K", "Zn_K"})
        self.assertEqual(sample.channels["Fe_K"].name, "Fe_K")

    def test_tiff_filename_proposal_recognizes_element_and_shell(self):
        proposal = infer_tiff_import("sample_control_P_K.tiff")
        self.assertEqual(proposal.sample_name, "sample_control")
        self.assertEqual(proposal.channel_key, "P_K")
        self.assertEqual(proposal.channel_name, "P_K")

        unknown = infer_tiff_import("phase_contrast.tif")
        self.assertEqual(unknown.sample_name, "phase_contrast")
        self.assertEqual(unknown.channel_key, "phase_contrast")

    def test_tiff_filename_prefers_shell_qualified_channel_token(self):
        proposal = infer_tiff_import("control_in_region_Fe_K.tiff")

        self.assertEqual(proposal.sample_name, "control_in_region")
        self.assertEqual(proposal.channel_key, "Fe_K")

    def test_tiff_can_be_added_to_existing_sample_with_edited_key(self):
        fe_path = self.make_tiff("sample_Fe_K.tif")
        zn_path = self.make_tiff("another_name.tif")
        project = ProjectData()
        sample = project.register_source(self.open(fe_path))

        same = project.register_source(
            self.open(zn_path),
            sample_id=sample.sample_id,
            channel_names={"page/0": ("Zn_K", "Zinc K")},
        )

        self.assertIs(same, sample)
        self.assertEqual(set(sample.channels), {"Fe_K", "Zn_K"})
        self.assertEqual(sample.channels["Zn_K"].name, "Zinc K")
        self.assertEqual(len(sample.asset_ids), 2)

    def test_multichannel_tiffs_get_unique_file_and_component_keys(self):
        paths = []
        base = np.arange(12).reshape(3, 4)
        for name, offset in (("first.tif", 0), ("second.tif", 100)):
            path = self.root / name
            data = np.stack([base + offset + component for component in range(4)], axis=-1).astype(
                "uint16"
            )
            tifffile.imwrite(path, data, photometric="rgb")
            paths.append(path)
        project = ProjectData()

        sample = project.register_source(self.open(paths[0]))
        project.register_source(self.open(paths[1]), sample_id=sample.sample_id)

        self.assertEqual(
            set(sample.channels),
            {
                "A-Red",
                "A-Green",
                "A-Blue",
                "A-Alpha",
                "B-Red",
                "B-Green",
                "B-Blue",
                "B-Alpha",
            },
        )
        self.assertEqual(
            [sample.channels[f"A-{color}"].name for color in ("Red", "Green", "Blue", "Alpha")],
            ["A-Red", "A-Green", "A-Blue", "A-Alpha"],
        )

    def test_hdf5_can_be_added_to_existing_sample(self):
        first = self.root / "first.h5"
        second = self.root / "second.h5"
        for path, key in ((first, "Fe"), (second, "Zn")):
            with h5py.File(path, "w") as handle:
                handle.attrs["default"] = "entry"
                handle.create_dataset(f"entry/plotselect/{key}", data=np.ones((3, 4)))
        project = ProjectData()
        sample = project.register_source(self.open(first))

        same = project.register_source(self.open(second), sample_id=sample.sample_id)

        self.assertIs(same, sample)
        self.assertEqual(set(sample.channels), {"Fe", "Zn"})

    def test_single_channel_tiff_key_can_be_renamed(self):
        fe_path = self.make_tiff("sample_Fe.tif")
        zn_path = self.make_tiff("sample_Zn.tif")
        project = ProjectData()
        sample = project.register_source(self.open(fe_path))
        project.register_source(self.open(zn_path), sample_id=sample.sample_id)
        project.add_project_channel("Fe")

        old_key = project.rename_single_channel_tiff(str(fe_path), "Iron")

        self.assertEqual(old_key, "Fe")
        self.assertEqual(set(sample.channels), {"Iron", "Zn"})
        self.assertEqual(set(project.project_channels), {"Iron"})
        with self.assertRaisesRegex(ValueError, "already exists"):
            project.rename_single_channel_tiff(str(fe_path), "Zn")

    def test_removing_file_preserves_empty_sample(self):
        path = self.make_tiff("sample_Fe.tif")
        project = ProjectData()
        sample = project.register_source(self.open(path))

        project.remove_asset(str(path))

        self.assertIn(sample.sample_id, project.samples)
        self.assertFalse(sample.asset_ids)
        self.assertFalse(sample.channels)

    def test_incompatible_tiff_is_rejected_without_partial_registration(self):
        first_path = self.make_tiff("sample_Fe.tif", (3, 4))
        second_path = self.make_tiff("sample_Zn.tif", (4, 4))
        project = ProjectData()
        sample = project.register_source(self.open(first_path))
        original_channels = dict(sample.channels)

        with self.assertRaisesRegex(ValueError, "has shape"):
            project.register_source(self.open(second_path), sample_id=sample.sample_id)

        self.assertEqual(sample.channels, original_channels)
        self.assertNotIn(str(second_path), project.assets)
        self.assertNotIn(str(second_path), project.assets)

    def test_relocating_file_preserves_source_and_channel_references(self):
        original = self.make_tiff("sample_Fe.tif")
        replacement = self.make_tiff("moved_Fe.tif")
        project = ProjectData()
        source = self.open(original)
        sample = project.register_source(source)
        channel = next(iter(sample.channels.values()))
        data_source = channel.data_source

        project.replace_asset_path(str(original), str(replacement))

        self.assertIs(project.assets[str(original)].source, source)
        self.assertIs(channel.data_source, data_source)
        self.assertEqual(project.assets[str(original)].path, str(replacement))
        np.testing.assert_array_equal(data_source.array(), tifffile.imread(replacement))


if __name__ == "__main__":
    unittest.main()
