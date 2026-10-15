"""Project asset path serialization and relocation."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from exhale.project.project_tab import ProjectTab
from exhale.project.projectio import asset_path_from_json, asset_path_to_json


class ProjectPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_project_relative_path_follows_project_directory(self):
        old_project = self.root / "old"
        old_data = old_project / "data" / "scan.h5"
        old_data.parent.mkdir(parents=True)
        old_data.touch()
        obj = asset_path_to_json(
            SimpleNamespace(path=str(old_data), original_path=str(old_data)), old_project, None
        )
        new_project = self.root / "new"
        new_data = new_project / "data" / "scan.h5"
        new_data.parent.mkdir(parents=True)
        new_data.touch()

        resolved = asset_path_from_json(obj, new_project, None)

        self.assertEqual(resolved, str(new_data.resolve()))
        self.assertEqual(obj["project_relative"], "data/scan.h5")

    def test_external_relative_path_uses_replacement_root(self):
        old_root = self.root / "old-data"
        old_data = old_root / "condition" / "scan.h5"
        old_data.parent.mkdir(parents=True)
        old_data.touch()
        obj = asset_path_to_json(
            SimpleNamespace(path=str(old_data), original_path=str(old_data)),
            self.root / "project",
            old_root,
        )
        new_root = self.root / "new-data"
        new_data = new_root / "condition" / "scan.h5"
        new_data.parent.mkdir(parents=True)
        new_data.touch()

        resolved = asset_path_from_json(obj, self.root / "project", new_root)

        self.assertEqual(resolved, str(new_data.resolve()))
        self.assertEqual(obj["absolute"], str(old_data.resolve()))
        self.assertEqual(obj["external_relative"], "condition/scan.h5")

    def test_tree_labels_normalize_mixed_relative_and_absolute_paths(self):
        first = self.root / "first" / "one.h5"
        second = self.root / "second" / "two.h5"
        relative_first = os.path.relpath(first)

        labels, common = ProjectTab._path_labels([relative_first, str(second)])

        self.assertEqual(common, self.root)
        self.assertEqual(labels[relative_first], "first/one.h5")
        self.assertEqual(labels[str(second)], "second/two.h5")


if __name__ == "__main__":
    unittest.main()
