"""Round-trip tests for segmentation-result sidecars."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from exhale.analysis.segmentationio import load_xrf_sample, save_xrf_sample
from exhale.xrf_refcopy.xrf_element_channel import ElementChannel
from exhale.xrf_refcopy.xrf_other_channel import NucleiChannel, TissueChannel
from exhale.xrf_refcopy.xrf_sample_class import XRFSample


class SegmentationIoTests(unittest.TestCase):
    def test_xrf_sample_round_trip_preserves_viewer_and_export_data(self):
        raw = np.arange(12, dtype=np.float32).reshape(3, 4)
        sample = XRFSample("Sample A")
        sample.nuclei = NucleiChannel(raw)
        sample.nuclei.nuclei_labels = np.array(
            [[0, 1, 1, 0], [0, 1, 1, 0], [0, 0, 0, 0]], dtype=np.int32
        )
        sample.nuclei.expanded_labels = sample.nuclei.nuclei_labels.copy()
        sample.nuclei.membrane_labels = np.zeros_like(sample.nuclei.nuclei_labels)
        sample.nuclei._processed = True
        sample.tissue = TissueChannel(raw + 1)
        sample.tissue.log_image = raw / 10
        sample.tissue.tissue_mask = raw > 2
        sample.tissue.tissue_labels = sample.tissue.tissue_mask.astype(np.int32)
        sample.tissue._processed = True
        channel = ElementChannel("Fe", raw + 2)
        channel.log_image = raw / 5
        channel.cluster_labels = sample.nuclei.nuclei_labels.copy()
        channel.intensity_thresholds = np.array([0.2, 0.8])
        channel.cluster_df = pd.DataFrame(
            [{"label": 1, "area": 4.0, "mean_intensity": 3.5, "centroid-0": 0.5}]
        )
        channel._processed = True
        sample.elements["Fe"] = channel
        sample._df_nuclei = pd.DataFrame(
            [
                {
                    "label": 1,
                    "element": "Fe",
                    "cluster_sizes": np.array([4.0]),
                    "cluster_intensities": np.array([3.5]),
                }
            ]
        )
        sample._df_membrane = pd.DataFrame(columns=sample._df_nuclei.columns)
        sample._df_background = pd.DataFrame(columns=sample._df_nuclei.columns)
        sample.results_df = pd.DataFrame([{"element": "Fe", "cluster_size": 4.0}])
        sample._processed = True
        sample._combined = True

        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "result.h5"
            save_xrf_sample(sample, filename)
            restored = load_xrf_sample(filename)

        self.assertEqual(restored.name, "Sample A")
        self.assertTrue(restored.is_processed)
        self.assertTrue(restored.is_combined)
        np.testing.assert_array_equal(restored.nuclei.nuclei_labels, sample.nuclei.nuclei_labels)
        np.testing.assert_array_equal(restored.tissue.tissue_mask, sample.tissue.tissue_mask)
        np.testing.assert_array_equal(
            restored.elements["Fe"].cluster_labels, channel.cluster_labels
        )
        self.assertEqual(restored.df_nuclei.iloc[0]["cluster_sizes"], [4.0])
        pd.testing.assert_frame_equal(restored.results_df, sample.results_df)


if __name__ == "__main__":
    unittest.main()
