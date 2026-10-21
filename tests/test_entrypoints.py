"""Public launchers must expose the same CLI without starting the GUI."""

import os
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
            self.assertIn("--install-desktop", output)
            self.assertIn("--remove-desktop", output)
            self.assertIn("--version", output)

    def test_desktop_registration_uses_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_home = Path(temporary_directory)
            with (
                patch.dict(os.environ, {"XDG_DATA_HOME": str(data_home)}),
                patch.object(exhale_main, "_desktop_command", return_value=("/opt/exhale",)),
            ):
                exhale_main._install_desktop()
                desktop_path, icon_path = exhale_main._desktop_paths()

                desktop_entry = desktop_path.read_text(encoding="utf-8")
                self.assertIn('Exec="/opt/exhale" %F', desktop_entry)
                self.assertIn("Icon=io.github.ctroein.Exhale", desktop_entry)
                self.assertEqual(
                    icon_path.read_bytes(),
                    exhale_main.resdir.joinpath("icons", "xrf.png").read_bytes(),
                )

                exhale_main._remove_desktop()
                self.assertFalse(desktop_path.exists())
                self.assertFalse(icon_path.exists())

    def test_desktop_command_preserves_public_launcher_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            target = directory / "private-exhale"
            target.touch()
            launcher = directory / "exhale"
            launcher.symlink_to(target)

            with patch.object(sys, "argv", [str(launcher), "--install-desktop"]):
                command = exhale_main._desktop_command()

            self.assertEqual(command, (str(launcher),))

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
