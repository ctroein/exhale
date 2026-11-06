"""Release filtering, installation identity, and detached Linux update behavior."""

import json
import os
import subprocess
import sys
import time

import pytest

from exhale import updates

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux updater")


@pytest.fixture
def tool(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    prefix = tools / "exhale-xrf"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib/exhale").mkdir(parents=True)
    launcher = prefix / "bin/exhale"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    uv = tmp_path / "uv"
    uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "{tools}"\n')
    uv.chmod(0o755)
    receipt = (
        '[tool]\nrequirements = [{name = "exhale-xrf", extras = ["cellpose", "monai"]}]\n'
        f'entrypoints = [{{name = "exhale", install-path = "{launcher}"}}]\n'
    )
    (prefix / "uv-receipt.toml").write_text(receipt)
    return prefix, uv


def test_identifies_only_matching_uv_tool(tool, tmp_path):
    prefix, uv = tool
    result = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    assert result["prefix"] == str(prefix)
    assert 'extras = ["cellpose", "monai"]' in result["receipt"]
    with pytest.raises(ValueError, match="source checkout"):
        updates.tool_installation(prefix, tmp_path / "checkout", str(uv))
    with pytest.raises(ValueError, match="not the exhale-xrf tool"):
        updates.tool_installation(tmp_path, tmp_path / "lib", str(uv))


def test_refuses_unwritable_installation(tool, monkeypatch):
    prefix, uv = tool
    monkeypatch.setattr(updates.os, "access", lambda *_args: False)
    with pytest.raises(ValueError, match="owned and writable"):
        updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))


def test_refuses_other_owner(tool, monkeypatch):
    prefix, uv = tool
    monkeypatch.setattr(updates.os, "getuid", lambda: prefix.stat().st_uid + 1)
    with pytest.raises(ValueError, match="owned and writable"):
        updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))


def test_release_check_excludes_yanked_prereleases_and_incompatible_python():
    data = {
        "releases": {
            "1.0": [{}],
            "1.1": [{"requires_python": ">=3.11"}],
            "1.2": [{"yanked": True}],
            "1.3rc1": [{}],
            "1.4.dev1": [{}],
            "1.5": [{"requires_python": ">=3.13"}],
            "invalid": [{}],
            "2.0": [],
        }
    }
    assert updates.latest_release(data, "1.0", "3.12.2") == "1.1"
    assert updates.latest_release(data, "1.1", "3.12.2") is None
    assert updates.latest_release(data, "1.0", "3.13.0") == "1.5"


def test_upgrade_preserves_uv_settings_and_runs_startup_check(tool, tmp_path, monkeypatch):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    job = updates.prepare_update({**plan, "version": "2.0"}, tmp_path / "updates")
    calls = []
    original = subprocess.run

    def run(command, **kwargs):
        if command[1:] == ["tool", "dir"]:
            return original(command, **kwargs)
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(updates.subprocess, "run", run)
    updates.run_update(job)
    assert calls[0][0] == [str(uv), "tool", "upgrade", "exhale-xrf"]
    assert calls[-1][0] == [str(prefix / "bin/exhale"), "--startup-check"]
    assert calls[-1][1]["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert (prefix / "uv-receipt.toml").read_text() == plan["receipt"]


def test_changed_receipt_prevents_upgrade(tool, tmp_path):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    job = updates.prepare_update({**plan, "version": "2.0"}, tmp_path / "updates")
    with (prefix / "uv-receipt.toml").open("a") as stream:
        stream.write("# another installation changed this\n")
    with pytest.raises(ValueError, match="changed after"):
        updates.run_update(job)


def test_copied_helper_waits_for_parent_and_records_failure(tool, tmp_path):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    # No actual package installation: fake uv deliberately rejects upgrade.
    upgraded = tmp_path / "upgrade-attempted"
    uv.write_text(
        '#!/bin/sh\nif [ "$2" = "dir" ]; then\n'
        f'printf "%s\\n" "{prefix.parent}"\nelse\ntouch "{upgraded}"\nexit 1\nfi\n'
    )
    job = updates.prepare_update({**plan, "version": "2.0"}, tmp_path / "updates")
    read_fd, write_fd = os.pipe()
    with (job / "update.log").open("wb") as log:
        process = subprocess.Popen(
            [sys._base_executable, "-I", str(job / "helper.py"), str(job), str(read_fd)],
            pass_fds=(read_fd,),
            stdout=log,
            stderr=log,
        )
    os.close(read_fd)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.3)
        assert not upgraded.exists()
    finally:
        os.close(write_fd)
        process.wait(timeout=10)
    assert upgraded.exists()
    assert json.loads((job / "result.json").read_text())["success"] is False
    assert "CalledProcessError" in (job / "update.log").read_text()


def test_running_instance_prevents_upgrade(tool):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    with updates.installation_lock(plan, exclusive=False):
        with pytest.raises(RuntimeError, match="Another Exhale instance"):
            updates.installation_lock(plan, exclusive=True)
    with updates.installation_lock(plan, exclusive=True):
        with pytest.raises(RuntimeError, match="Another Exhale instance"):
            updates.installation_lock(plan, exclusive=False)


def test_upgrade_failure_does_not_run_startup_check(tool, tmp_path, monkeypatch):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    job = updates.prepare_update({**plan, "version": "2.0"}, tmp_path / "updates")
    original = subprocess.run
    calls = []

    def run(command, **kwargs):
        if command[1:] == ["tool", "dir"]:
            return original(command, **kwargs)
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(updates.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        updates.run_update(job)
    assert calls == [[str(uv), "tool", "upgrade", "exhale-xrf"]]


@pytest.mark.parametrize("startup_code", [0, 1])
def test_helper_records_startup_result_and_reopens(tool, tmp_path, startup_code):
    prefix, uv = tool
    plan = updates.tool_installation(prefix, prefix / "lib/exhale", str(uv))
    restarted = tmp_path / "restarted"
    launcher = prefix / "bin/exhale"
    launcher.write_text(
        '#!/bin/sh\nif [ "$1" = "--startup-check" ]; then\n'
        f'exit {startup_code}\nfi\ntouch "{restarted}"\n'
    )
    python = prefix / "bin/python"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    uv.write_text(f'#!/bin/sh\nif [ "$2" = "dir" ]; then\nprintf "%s\\n" "{prefix.parent}"\nfi\n')
    job = updates.prepare_update({**plan, "version": "2.0"}, tmp_path / "updates")
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    # Run through the isolated copied helper, with no real uv or package operations.
    subprocess.run(
        [sys._base_executable, "-I", str(job / "helper.py"), str(job), str(read_fd)],
        pass_fds=(read_fd,),
        check=True,
        capture_output=True,
        timeout=10,
    )
    os.close(read_fd)
    assert json.loads((job / "result.json").read_text())["success"] == (startup_code == 0)
    # The restarted script can be scheduled after the helper process exits.
    deadline = time.monotonic() + 5
    while not restarted.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert restarted.exists()
