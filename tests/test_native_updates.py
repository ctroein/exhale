"""Native launcher identity and update handoff without modifying a real installation."""

import json

import pytest

from exhale import updates


@pytest.fixture(params=["windows", "macos"])
def native(tmp_path, monkeypatch, request):
    root = tmp_path / "installation"
    prefix = root / "runtime/env-active"
    prefix.mkdir(parents=True)
    state = {"environment": prefix.name, "wheel": "bundled.whl", "backends": "both"}
    (root / "runtime/installed.json").write_text(json.dumps(state))
    descriptor = {"protocol": "1", "kind": request.param, "root": str(root), "token": "instance"}
    monkeypatch.setenv("EXHALE_NATIVE_INSTALLATION", json.dumps(descriptor))
    monkeypatch.setattr(updates.sys, "prefix", str(prefix))
    monkeypatch.setattr(
        updates.sys, "platform", "win32" if request.param == "windows" else "darwin"
    )
    monkeypatch.setattr(updates, "__file__", str(prefix / "lib/exhale/updates.py"))
    return root, prefix


def test_native_handoff_targets_only_the_current_parent(native, tmp_path):
    root, prefix = native
    installation = updates.installation()
    assert installation["prefix"] == str(prefix)
    job = updates.prepare_update({**installation, "version": "2.0"}, tmp_path / "jobs")
    assert not (job / "helper.py").exists()
    assert not (root / "update-request.json").exists()
    updates.launch_update(job)
    assert json.loads((root / "update-request.json").read_text()) == {
        "version": "2.0",
        "environment": "env-active",
        "token": "instance",
        "job": str(job),
    }


def test_native_handoff_rejects_changed_runtime(native, tmp_path):
    root, _prefix = native
    job = updates.prepare_update({**updates.installation(), "version": "2.0"}, tmp_path / "jobs")
    state_path = root / "runtime/installed.json"
    state_path.write_text(state_path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed after"):
        updates.launch_update(job)
    assert not (root / "update-request.json").exists()


def test_native_identity_rejects_an_unrelated_interpreter(native, monkeypatch):
    root, _prefix = native
    monkeypatch.setattr(updates.sys, "prefix", str(root / "other-env"))
    with pytest.raises(ValueError, match="does not own"):
        updates.installation()
