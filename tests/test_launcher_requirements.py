"""Native launcher requirements must gate updates without affecting uv installations."""

import io
import json
import urllib.error

import pytest

from exhale import updates


def test_launcher_requirements_accept_matching_and_reject_older_versions():
    requirements = {"windows": "2.0", "macos": "1.0"}
    updates.require_launcher("windows", "2.0", requirements)
    updates.require_launcher("macos", "1.5", requirements)
    with pytest.raises(ValueError, match="newer installer"):
        updates.require_launcher("windows", "1.9", requirements)
    with pytest.raises(ValueError, match="newer installer"):
        updates.require_launcher("windows", "0", requirements)


def test_release_requirement_uses_target_version_and_parent_launcher(monkeypatch):
    requests = []

    def fetch(url, **kwargs):
        requests.append(url)
        return io.BytesIO(json.dumps({"windows": "2.0", "macos": "0"}).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fetch)
    with pytest.raises(ValueError, match="2.0"):
        updates.check_release_launcher({"kind": "windows", "launcher_version": "1.5"}, "3.0")
    assert requests == [
        "https://raw.githubusercontent.com/ctroein/exhale/v3.0/exhale/launcher_requirements.json"
    ]
    updates.check_release_launcher({"kind": "windows", "launcher_version": "2.0"}, "3.0")


def test_old_release_without_requirements_remains_updatable(monkeypatch):
    def fetch(url, **kwargs):
        raise urllib.error.HTTPError(url, 404, "Not found", {}, None)

    monkeypatch.setattr(updates.urllib.request, "urlopen", fetch)
    updates.check_release_launcher({"kind": "windows"}, "1.5.3")


def test_candidate_check_enforces_packaged_requirement(tmp_path, monkeypatch):
    (tmp_path / "launcher_requirements.json").write_text('{"windows": "2.0", "macos": "0"}')
    monkeypatch.setattr(updates, "__file__", str(tmp_path / "updates.py"))
    monkeypatch.delenv("EXHALE_NATIVE_INSTALLATION", raising=False)
    monkeypatch.setenv("EXHALE_LAUNCHER_KIND", "windows")
    monkeypatch.setenv("EXHALE_LAUNCHER_VERSION", "1.5")
    with pytest.raises(ValueError, match="newer installer"):
        updates.check_running_launcher()
    monkeypatch.setenv("EXHALE_LAUNCHER_VERSION", "2.0")
    updates.check_running_launcher()


def test_linux_tool_updates_do_not_fetch_native_requirements(monkeypatch):
    def fetch(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(updates.urllib.request, "urlopen", fetch)
    updates.check_release_launcher({"uv": "/usr/bin/uv"}, "3.0")


def test_legacy_native_candidate_is_checked_as_version_zero(tmp_path, monkeypatch):
    (tmp_path / "launcher_requirements.json").write_text('{"windows": "2.0", "macos": "0"}')
    monkeypatch.setattr(updates, "__file__", str(tmp_path / "updates.py"))
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path / "runtime/env-candidate"))
    monkeypatch.delenv("EXHALE_NATIVE_INSTALLATION", raising=False)
    monkeypatch.delenv("EXHALE_LAUNCHER_KIND", raising=False)
    monkeypatch.delenv("EXHALE_LAUNCHER_VERSION", raising=False)
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "runtime/python"))
    with pytest.raises(ValueError, match="Installed launcher/setup: 0"):
        updates.check_running_launcher()
