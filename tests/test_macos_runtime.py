"""Private macOS runtime ownership, backend choices and failed-update recovery."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fcntl")
_spec = importlib.util.spec_from_file_location(
    "macos_runtime", Path(__file__).resolve().parents[1] / "packaging/macos/runtime.py"
)
runtime_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime_module)


@pytest.fixture
def runtime(tmp_path):
    resources = tmp_path / "EXHALE.app/Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "setup.json").write_text(
        json.dumps({"wheel": "exhale_xrf-1.0-py3-none-any.whl", "architecture": "arm64"})
    )
    return runtime_module.Runtime(resources, tmp_path / "Application Support/EXHALE")


@pytest.mark.parametrize("selection", runtime_module.BACKENDS)
def test_selection_installs_only_requested_extras_and_checks_before_commit(runtime, selection):
    commands = []

    def run(command):
        commands.append(list(map(str, command)))
        if command[1] == "venv":
            Path(command[-1]).mkdir()
        if "--startup-check" in command:
            assert not runtime.state_path.exists()

    runtime.run = run
    with runtime.locked():
        runtime.install(selection)
    requirement = commands[1][7]
    extras = runtime_module.BACKENDS[selection]
    assert (
        requirement.endswith("[" + ",".join(extras) + "]")
        if extras
        else requirement.endswith(".whl")
    )
    assert ("-r" in commands[1]) == ("cellpose" in extras)
    assert commands[2][-3:] == ["-m", "exhale", "--startup-check"]
    assert runtime.state()["backends"] == selection


def test_failed_update_keeps_previous_environment_and_record(runtime):
    runtime.root.mkdir(parents=True)
    previous = runtime.root / "env-previous"
    previous.mkdir()
    state = {"environment": previous.name, "wheel": "old.whl", "backends": "none"}
    runtime.state_path.write_text(json.dumps(state))

    def run(command):
        if command[1] == "venv":
            Path(command[-1]).mkdir()
        if "--startup-check" in command:
            raise subprocess.CalledProcessError(1, command)

    runtime.run = run
    with runtime.locked(), pytest.raises(subprocess.CalledProcessError):
        runtime.install("both")
    assert runtime.state() == state
    assert sorted(runtime.root.glob("env-*")) == [previous]


def test_remove_is_private_and_preserves_projects(runtime):
    project = runtime.home / "project.h5"
    runtime.home.mkdir(parents=True)
    project.write_text("project")
    runtime.root.mkdir()
    (runtime.root / "private-python").write_text("runtime")
    with runtime.locked():
        runtime.remove()
    assert project.read_text() == "project"
    assert not runtime.root.exists()


def test_second_process_cannot_modify_active_runtime(runtime):
    with runtime.locked(), pytest.raises(RuntimeError, match="already running"):
        with runtime.locked():
            pytest.fail("second runtime lock should not succeed")


def test_intel_rejects_cellpose_before_downloading(runtime):
    runtime.config["architecture"] = "x86_64"
    runtime.run = lambda _command: pytest.fail("unsupported backend must not download")
    with runtime.locked(), pytest.raises(ValueError, match="Apple Silicon"):
        runtime.install("cellpose")


def test_runtime_does_not_inherit_other_python_or_uv_environments(runtime, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/other/project")
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", "/other/python")
    monkeypatch.setenv("VIRTUAL_ENV", "/other/venv")
    isolated = runtime_module.Runtime(runtime.resources, runtime.home)
    assert "PYTHONPATH" not in isolated.env
    assert "VIRTUAL_ENV" not in isolated.env
    assert isolated.env["UV_PYTHON_INSTALL_DIR"] == str(isolated.root / "python")


def test_launch_requires_current_bundle_and_uses_private_interpreter(runtime):
    runtime.root.mkdir(parents=True)
    runtime.state_path.write_text(
        json.dumps(
            {"environment": "env-working", "wheel": runtime.config["wheel"], "backends": "none"}
        )
    )
    commands = []
    runtime.run = commands.append
    runtime.launch([])
    assert commands == [[runtime.root / "env-working/bin/python", "-m", "exhale"]]
    runtime.config["wheel"] = "new.whl"
    with pytest.raises(RuntimeError, match="setup"):
        runtime.launch([])


def test_builder_bundles_local_release_and_private_setup(tmp_path, monkeypatch):
    import io
    import plistlib
    from zipfile import ZipFile

    spec = importlib.util.spec_from_file_location(
        "macos_build", Path(__file__).resolve().parents[1] / "packaging/macos/build.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    wheel = tmp_path / "exhale_xrf-1.2.3-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "exhale_xrf-1.2.3.dist-info/METADATA", "Name: exhale-xrf\nVersion: 1.2.3\n"
        )
    output = tmp_path / "dist"
    monkeypatch.setattr(builder.sys, "platform", "darwin")
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        builder.sys, "argv", ["build", "--wheel", str(wheel), "--output", str(output)]
    )
    monkeypatch.setattr(builder, "download_uv", lambda _arch, path: path.write_text("uv"))
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(b"uv license")
    )
    commands = []
    monkeypatch.setattr(builder.subprocess, "run", lambda command, **_kw: commands.append(command))
    builder.main()
    resources = output / "EXHALE.app/Contents/Resources"
    config = json.loads((resources / "setup.json").read_text())
    assert config == {"wheel": wheel.name, "architecture": "arm64"}
    assert (resources / wheel.name).read_bytes() == wheel.read_bytes()
    assert (resources / "runtime.py").exists()
    assert (resources / "requirements-cellpose.txt").exists()
    with (resources.parent / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleExecutable"] == "EXHALE"
    assert info["CFBundleShortVersionString"] == "1.2.3"
    assert (output / "dmg-arm64/Applications").is_symlink()
    assert any(command[:2] == ["codesign", "--verify"] for command in commands)
