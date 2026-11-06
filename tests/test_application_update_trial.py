"""Local update trial server, build isolation, and uv/application state separation."""

import importlib.util
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from exhale import updates

_spec = importlib.util.spec_from_file_location(
    "application_update_trial",
    Path(__file__).resolve().parents[1] / "tools/try_application_update.py",
)
trial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trial)


@pytest.fixture
def server(tmp_path):
    wheels = []
    for version in trial.VERSIONS:
        path = tmp_path / f"exhale_xrf-{version}-py3-none-any.whl"
        path.write_bytes(version.encode())
        wheels.append(path)
    with trial.TrialIndex(wheels) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def test_index_hides_new_release_until_first_install_finishes(server, monkeypatch):
    url = f"{server.url}/simple/exhale-xrf/"
    with urllib.request.urlopen(url) as response:
        page = response.read().decode()
    assert server.wheels[0].name in page
    assert server.wheels[1].name not in page
    assert "#sha256=" in page
    monkeypatch.setenv("EXHALE_UPDATE_TEST_URL", f"{server.url}/pypi/exhale-xrf/json")
    assert updates.check_release(trial.VERSIONS[0]) is None
    server.offer_update = True
    assert updates.check_release(trial.VERSIONS[0]) == trial.VERSIONS[1]
    with urllib.request.urlopen(url) as response:
        assert server.wheels[1].name in response.read().decode()


def test_index_serves_only_its_wheels_and_allows_dependency_fallback(server):
    with urllib.request.urlopen(f"{server.url}/wheels/{server.wheels[0].name}") as response:
        assert response.read() == trial.VERSIONS[0].encode()
    for path in ("/simple/numpy/", "/wheels/../../secret", f"/wheels/{server.wheels[1].name}"):
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(server.url + path)
        assert error.value.code == 404


def test_head_reports_same_headers_as_get_without_a_body(server):
    for path in (
        "/simple/exhale-xrf/",
        "/pypi/exhale-xrf/json",
        f"/wheels/{server.wheels[0].name}",
    ):
        with urllib.request.urlopen(server.url + path) as response:
            length = len(response.read())
            content_type = response.headers["Content-Type"]
        request = urllib.request.Request(server.url + path, method="HEAD")
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
            assert int(response.headers["Content-Length"]) == length
            assert response.headers["Content-Type"] == content_type
            assert response.read() == b""


def test_trial_environment_keeps_shared_cache_and_isolates_user_state(tmp_path, monkeypatch):
    monkeypatch.setenv("UV_CACHE_DIR", "/test/shared-cache")
    before = dict(os.environ)
    environment = trial.trial_environment(tmp_path, "http://127.0.0.1:12345")
    assert environment["UV_CACHE_DIR"] == "/test/shared-cache"
    assert environment["UV_TOOL_DIR"] == str(tmp_path / "tools")
    assert environment["UV_TOOL_BIN_DIR"] == str(tmp_path / "bin")
    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "config")
    assert environment["XDG_DATA_HOME"] == str(tmp_path / "data")
    assert os.environ == before


def test_builds_snapshot_versions_without_changing_checkout(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        (root / name).write_text("test")
    (root / "exhale").mkdir()
    (root / "exhale/__init__.py").write_text("original source")
    directory = tmp_path / "trial"
    directory.mkdir()
    monkeypatch.setattr(trial, "ROOT", root)
    commands = []

    def build(command, *, check, env):
        version = env["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EXHALE_XRF"]
        commands.append((command, version))
        assert command[command.index("--python") + 1] == trial.sys.executable
        (directory / "wheels").mkdir(exist_ok=True)
        (directory / "wheels" / f"exhale_xrf-{version}-py3-none-any.whl").touch()
        assert command[-1] == str(directory / "source")

    monkeypatch.setattr(trial.subprocess, "run", build)
    wheels = trial.build_wheels(directory, "uv")
    assert [v for _c, v in commands] == list(trial.VERSIONS)
    assert len(wheels) == 2
    assert (root / "exhale/__init__.py").read_text() == "original source"
    assert not (root / "build").exists()


def test_test_endpoint_override_is_loopback_only(monkeypatch):
    monkeypatch.setenv("EXHALE_UPDATE_TEST_URL", "https://example.com/releases.json")
    with pytest.raises(ValueError, match="127.0.0.1"):
        updates.check_release("1.0")
