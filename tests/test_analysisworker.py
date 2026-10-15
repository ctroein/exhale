"""Tests for analysis-worker output handling."""

import os
import unittest

from exhale.analysis.analysisworker import capture_native_stderr


class AnalysisWorkerTests(unittest.TestCase):
    def test_native_stderr_is_captured_line_by_line(self):
        messages = []

        with capture_native_stderr(messages.append):
            os.write(2, b"native first line\nnative second line\n")

        self.assertEqual(messages, ["native first line", "native second line"])


if __name__ == "__main__":
    unittest.main()
