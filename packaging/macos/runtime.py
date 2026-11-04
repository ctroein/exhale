"""Manage the macOS launcher's private uv runtime without modifying the app bundle."""

import argparse
import contextlib
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

BACKENDS = {
    "none": (),
    "stardist": ("stardist",),
    "cellpose": ("cellpose",),
    "both": ("stardist", "cellpose"),
}


class Runtime:
    """Install atomically selected environments and keep their ownership local to EXHALE."""

    def __init__(self, resources, home):
        self.resources = Path(resources)
        self.home = Path(home)
        self.root = self.home / "runtime"
        self.state_path = self.root / "installed.json"
        self.config = json.loads((self.resources / "setup.json").read_text())
        self.uv = self.resources / "uv"
        self.env = os.environ.copy()
        for name in tuple(self.env):
            if name.startswith(("UV_", "PIP_", "PYTHON")) or name in (
                "VIRTUAL_ENV",
                "__PYVENV_LAUNCHER__",
                "QT_API",
                "QT_PLUGIN_PATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH",
            ):
                self.env.pop(name)
        self.env.update(
            UV_PYTHON_INSTALL_DIR=str(self.root / "python"),
            UV_PYTHON_BIN_DIR=str(self.root / "bin"),
            UV_CACHE_DIR=str(self.root / "cache"),
            UV_PYTHON_PREFERENCE="only-managed",
            UV_NO_CONFIG="1",
            UV_NO_PROGRESS="1",
            PYTHONUNBUFFERED="1",
            QT_API="pyqt6",
        )

    @contextlib.contextmanager
    def locked(self):
        """Prevent setup, removal, or a second launch while this runtime is in use."""
        self.home.mkdir(parents=True, exist_ok=True)
        with (self.home / "setup.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "EXHALE or its setup is already running. Close it first."
                ) from error
            yield

    def state(self):
        try:
            state = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return None
        name = state["environment"]
        if not name.startswith("env-") or Path(name).name != name:
            raise ValueError("Invalid runtime environment in installation record")
        return state

    def run(self, arguments):
        print("Running:", " ".join(map(str, arguments)), flush=True)
        env = self.env
        if "--startup-check" in arguments:
            env = dict(env, QT_QPA_PLATFORM="offscreen")
        subprocess.run(list(map(str, arguments)), env=env, cwd=self.home, check=True)

    def install(self, selection):
        """Validate a fresh environment before switching the launch record to it."""
        self.root.mkdir(parents=True, exist_ok=True)
        environment = self.root / ("env-" + uuid4().hex)
        previous = self.state()
        wheel = self.resources / self.config["wheel"]
        extras = BACKENDS[selection]
        if "cellpose" in extras and self.config["architecture"] == "x86_64":
            raise ValueError(
                "Cellpose requires Apple Silicon; its PyTorch dependency has no Intel Mac wheels."
            )
        if (
            "cellpose" in extras
            and sys.platform == "darwin"
            and int(platform.mac_ver()[0].split(".")[0]) < 14
        ):
            raise ValueError("Cellpose requires macOS 14 or later.")
        requirement = str(wheel) + ("[" + ",".join(extras) + "]" if extras else "")
        try:
            self.run([self.uv, "venv", "--python", "3.12", environment])
            command = [
                self.uv,
                "pip",
                "install",
                "--python",
                environment / "bin/python",
                "--prerelease",
                "disallow",
                requirement,
            ]
            if "cellpose" in extras:
                command += ["-r", self.resources / "requirements-cellpose.txt"]
            self.run(command)
            self.run([environment / "bin/python", "-m", "exhale", "--startup-check"])
            installed = {
                "environment": environment.name,
                "wheel": self.config["wheel"],
                "backends": selection,
            }
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(installed))
            temporary.replace(self.state_path)
        except BaseException:
            if environment.exists():
                shutil.rmtree(environment)
            raise
        if previous:
            old = self.root / previous["environment"]
            if old.exists():
                shutil.rmtree(old)
        print("Setup completed.", flush=True)

    def launch(self, arguments):
        state = self.state()
        if state is None or state["wheel"] != self.config["wheel"]:
            raise RuntimeError("Run EXHALE setup for this application version first.")
        self.run([self.root / state["environment"] / "bin/python", "-m", "exhale", *arguments])

    def remove(self):
        if self.root.exists():
            shutil.rmtree(self.root)
        print("Private Python runtime removed. Projects and application settings were retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("action", choices=("install", "launch", "remove"))
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    runtime = Runtime(args.resources, args.home)
    with runtime.locked():
        if args.action == "install":
            if len(args.arguments) != 1 or args.arguments[0] not in BACKENDS:
                parser.error("install requires none, stardist, cellpose, or both")
            runtime.install(args.arguments[0])
        elif args.action == "launch":
            runtime.launch(args.arguments)
        else:
            runtime.remove()


if __name__ == "__main__":
    main()
