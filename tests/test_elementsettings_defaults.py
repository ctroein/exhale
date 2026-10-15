"""Adaptive defaults copied into new element settings and projects."""

import unittest

import numpy as np

from exhale.data.elementsettings import ElementSettings, ElementSettingsDefaults, Normalizers
from exhale.data.projectdata import ProjectData
from exhale.data.source_refs import ElementRef


class ElementSettingsDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.ref = ElementRef("scan.h5", "/entry/plotselect/P_K")
        self.data = np.arange(101, dtype=float).reshape(101, 1)

    def test_percentile_defaults_are_evaluated_for_new_settings(self):
        defaults = ElementSettingsDefaults(
            normalizer=Normalizers.GAMMA,
            range_mode="percent",
            lower_percentile=10,
            upper_percentile=90,
            gamma=1.5,
        )

        element = ElementSettings(self.ref, data=self.data, defaults=defaults)

        self.assertEqual(element.normalizer, Normalizers.GAMMA)
        self.assertEqual(element.gamma, 1.5)
        np.testing.assert_allclose(element.trfRange, [10, 90])

    def test_changing_project_defaults_does_not_change_existing_settings(self):
        project = ProjectData(ElementSettingsDefaults(range_mode="sd", standard_deviations=1))
        first = ElementSettings(self.ref, data=self.data, defaults=project.element_defaults)
        first_range = first.trfRange.copy()

        project.element_defaults.range_mode = "percent"
        project.element_defaults.lower_percentile = 25
        project.element_defaults.upper_percentile = 75
        second = ElementSettings(self.ref, data=self.data, defaults=project.element_defaults)

        self.assertEqual(first.trfRange, first_range)
        np.testing.assert_allclose(second.trfRange, [25, 75])

    def test_defaults_json_roundtrip_returns_independent_copy(self):
        defaults = ElementSettingsDefaults(
            normalizer=Normalizers.ARCSINH,
            range_mode="sd",
            standard_deviations=2,
            gamma=1.1,
        )

        restored = ElementSettingsDefaults.from_json(defaults.to_json())

        self.assertEqual(restored, defaults)
        self.assertIsNot(restored, defaults)


if __name__ == "__main__":
    unittest.main()
