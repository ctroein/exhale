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


def test_backend_retained_stream_is_safe_after_the_worker_finishes(monkeypatch):
    import io
    import sys

    from exhale.analysis.analysisworker import capture_analysis_output

    original = io.StringIO()
    monkeypatch.setattr(sys, "stderr", original)
    messages = []
    with capture_analysis_output(messages.append):
        retained = sys.stderr
        retained.write("during work\n")
    retained.write("after work\n")
    retained.flush()
    retained.close()
    assert messages == ["during work"]
    assert original.getvalue() == "after work\n"
    assert not original.closed
