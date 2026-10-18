"""Public launchers must expose the same CLI without starting the GUI."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exhale import __main__ as exhale_main
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
            result = subprocess.run(
                command + [argument], cwd=root, capture_output=True, text=True, timeout=15
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            results.append(result.stdout)
        return results

    def test_help_exposes_expected_options(self):
        for output in self.run_launchers("--help"):
            self.assertIn("--recompile", output)
            self.assertIn("--recompile-only", output)
            self.assertIn("--project", output)
            self.assertIn("--version", output)

    def test_recompile_only_rebuilds_all_ui_files_and_exits(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            resource_dir = Path(temporary_directory)
            ui_dir = resource_dir / "ui"
            ui_dir.mkdir()
            names = (
                "main_window",
                "image_settings_dialog",
                "analysis_settings_dialog",
                "settings_dialog",
            )
            for name in names:
                (ui_dir / f"{name}.ui").touch()

            with (
                patch.object(exhale_main, "resdir", resource_dir),
                patch.object(exhale_main, "_recompile_ui") as recompile,
                patch.object(sys, "argv", ["exhale", "--recompile-only"]),
            ):
                result = exhale_main._run_application()

        self.assertEqual(result, 0)
        self.assertEqual(recompile.call_count, len(names))

    def test_version_matches_package_metadata(self):
        for output in self.run_launchers("--version"):
            self.assertEqual(output.strip(), f"Exhale {exhale_version}")
