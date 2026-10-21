"""Tests for project channel and sample resolution."""

import unittest

from exhale.data.projectdata import (
    Channel,
    ChannelOverride,
    ProjectData,
    Sample,
    SampleChannelState,
    SegmentationParameters,
    SegmentationResult,
    shortest_unique_path_suffixes,
)
from exhale.data.source_refs import ElementRef


class ProjectDataTests(unittest.TestCase):
    def setUp(self):
        self.fe_ref = ElementRef("scan.h5", "/entry/plotselect/Fe")
        self.zn_ref = ElementRef("scan.h5", "/entry/plotselect/Zn")
        self.sample = Sample(
            sample_id="scan",
            name="Scan",
            channels={
                "Fe": Channel("Fe", "Iron raw", self.fe_ref, "fe-map"),
                "Zn": Channel("Zn", "Zinc raw", self.zn_ref, "zn-map"),
            },
        )
        self.project_channels = {
            "Fe": Channel("Fe", "Iron", settings="fe-default"),
        }

    def test_sample_inherits_project_channel(self):
        effective = self.sample.effective_channels(self.project_channels)
        self.assertEqual(set(effective), {"Fe"})
        self.assertEqual(effective["Fe"].name, "Iron")
        self.assertEqual(effective["Fe"].ref, self.fe_ref)
        self.assertEqual(effective["Fe"].settings, "fe-map")
        self.assertFalse(effective["Fe"].overridden)

    def test_sample_can_skip_override_and_add_channels(self):
        self.sample.channel_overrides["Fe"] = None
        self.sample.channel_overrides["Zn"] = ChannelOverride(
            name="Local zinc", settings="local-settings"
        )

        effective = self.sample.effective_channels(self.project_channels)

        self.assertEqual(set(effective), {"Zn"})
        self.assertEqual(effective["Zn"].name, "Local zinc")
        self.assertEqual(effective["Zn"].settings, "local-settings")
        self.assertTrue(effective["Zn"].overridden)

    def test_override_can_change_only_the_inherited_name(self):
        self.sample.channel_overrides["Fe"] = ChannelOverride(name="Local iron")

        channel = self.sample.effective_channels(self.project_channels)["Fe"]

        self.assertEqual(channel.name, "Local iron")
        self.assertEqual(channel.settings, "fe-map")

    def test_clear_preserves_element_settings_container_identity(self):
        project = ProjectData()
        elements = project.element_settings
        project.element_settings[self.fe_ref] = object()
        project.samples["scan"] = self.sample

        project.clear()

        self.assertIs(project.element_settings, elements)
        self.assertFalse(elements)
        self.assertFalse(project.samples)

    def test_segmentation_result_is_removed_with_its_sample(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        parameters = SegmentationParameters(5, 10, 2, 4)
        project.segmentation_results["scan"] = SegmentationResult(
            "scan",
            self.fe_ref,
            self.zn_ref,
            (self.fe_ref,),
            parameters,
            object(),
        )

        project.remove_sample("scan")

        self.assertNotIn("scan", project.segmentation_results)

    def test_clear_removes_segmentation_results(self):
        project = ProjectData()
        project.segmentation_results["scan"] = object()

        project.clear()

        self.assertFalse(project.segmentation_results)

    def test_materialized_settings_are_attached_to_sample_channel(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        settings = object()

        project.set_element_settings(self.fe_ref, settings)

        self.assertIs(project.element_settings[self.fe_ref], settings)
        self.assertIs(self.sample.channels["Fe"].settings, settings)

    def test_project_channel_can_be_inherited_skipped_and_overridden(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        project.add_project_channel("Fe", "Iron", "project-settings")

        self.assertEqual(project.sample_channel_state("scan", "Fe"), SampleChannelState.INHERIT)
        self.assertEqual(
            self.sample.effective_channels(project.project_channels)["Fe"].name, "Iron"
        )

        project.skip_sample_channel("scan", "Fe")
        self.assertEqual(project.sample_channel_state("scan", "Fe"), SampleChannelState.SKIP)
        self.assertNotIn("Fe", self.sample.effective_channels(project.project_channels))

        project.override_sample_channel("scan", "Fe", name="Local iron", settings="local")
        self.assertEqual(project.sample_channel_state("scan", "Fe"), SampleChannelState.OVERRIDE)
        resolved = self.sample.effective_channels(project.project_channels)["Fe"]
        self.assertEqual((resolved.name, resolved.settings), ("Local iron", "local"))

        project.inherit_sample_channel("scan", "Fe")
        self.assertEqual(project.sample_channel_state("scan", "Fe"), SampleChannelState.INHERIT)

    def test_local_channel_requires_an_override_to_be_selected(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        self.assertEqual(project.sample_channel_state("scan", "Zn"), SampleChannelState.SKIP)

        project.override_sample_channel("scan", "Zn")

        resolved = self.sample.effective_channels(project.project_channels)
        self.assertEqual(set(resolved), {"Zn"})
        self.assertEqual(resolved["Zn"].name, "Zinc raw")

        project.revert_sample_channel("scan", "Zn")
        self.assertNotIn("Zn", self.sample.effective_channels(project.project_channels))

    def test_single_sample_edit_targets_project(self):
        project = ProjectData()
        project.samples["scan"] = self.sample

        project.edit_channel("scan", "Fe", name="Project iron")

        self.assertEqual(project.project_channels["Fe"].name, "Project iron")
        self.assertNotIn("Fe", self.sample.channel_overrides)

    def test_multiple_sample_edit_creates_local_override(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        other_ref = ElementRef("other.h5", "/entry/plotselect/Fe")
        other = Sample(
            "other", "Other", channels={"Fe": Channel("Fe", "Iron other", other_ref, "other-map")}
        )
        project.samples["other"] = other
        project.add_project_channel("Fe", "Project iron")

        project.edit_channel("scan", "Fe", name="Scan iron")

        self.assertEqual(project.project_channels["Fe"].name, "Project iron")
        self.assertEqual(self.sample.channel_overrides["Fe"].name, "Scan iron")
        self.assertNotIn("Fe", other.channel_overrides)

    def test_removing_project_channel_preserves_explicit_local_use(self):
        project = ProjectData()
        project.samples["scan"] = self.sample
        project.add_project_channel("Fe", "Iron")
        project.override_sample_channel("scan", "Fe", name="Local iron")

        project.remove_project_channel("Fe")

        resolved = self.sample.effective_channels(project.project_channels)
        self.assertEqual(resolved["Fe"].name, "Local iron")

    def test_shortest_unique_filename_suffix_uses_path_components(self):
        paths = [
            "/data/control/scan/results.h5",
            "/data/treated/scan/results.h5",
            "/archive/results.h5",
        ]

        suffixes = shortest_unique_path_suffixes(paths)

        self.assertEqual(suffixes[paths[0]], "control/scan/results.h5")
        self.assertEqual(suffixes[paths[1]], "treated/scan/results.h5")
        self.assertEqual(suffixes[paths[2]], "archive/results.h5")


if __name__ == "__main__":
    unittest.main()
