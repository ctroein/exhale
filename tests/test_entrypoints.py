"""Public launchers must expose the same CLI without starting the GUI."""
from pathlib import Path
import subprocess
import sys
import unittest

from exhale import exhale_version


class EntrypointTests(unittest.TestCase):
    def run_launchers(self, argument):
        root = Path(__file__).resolve().parents[1]
        commands = (
            [sys.executable, "run_exhale.py"],
            [sys.executable, "-m", "exhale"],
            [sys.executable, "-c", "from exhale.__main__ import main; main()"],
        )
        results = []
        for command in commands:
            result = subprocess.run(command + [argument], cwd=root,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(result.stdout)
        return results

    def test_help_exposes_expected_options(self):
        for output in self.run_launchers("--help"):
            self.assertIn("--recompile", output)
            self.assertIn("--project", output)
            self.assertIn("--version", output)

    def test_version_matches_package_metadata(self):
        for output in self.run_launchers("--version"):
            self.assertEqual(output.strip(), f"Exhale {exhale_version}")
