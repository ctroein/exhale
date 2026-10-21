"""Version reporting distinguishes releases from source development."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from exhale import _version_from_git


def _git_description(description: str):
    return patch(
        "exhale.subprocess.run",
        return_value=Mock(stdout=f"{description}\n"),
    )


def test_exact_git_tag_is_release_version(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with _git_description("v1.4.1-0-g1234abc"):
        assert _version_from_git(tmp_path) == "1.4.1"


def test_commits_after_tag_are_development_version(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with _git_description("v1.4.1-7-g1234abc"):
        assert _version_from_git(tmp_path) == "1.4.1-dev"


def test_dirty_tag_is_development_version(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with _git_description("v1.4.1-0-g1234abc-dirty"):
        assert _version_from_git(tmp_path) == "1.4.1-dev"


def test_git_failure_uses_fallback(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with patch("exhale.subprocess.run", side_effect=subprocess.CalledProcessError(128, "git")):
        assert _version_from_git(tmp_path) is None
