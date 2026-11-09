"""Manage the macOS launcher's private uv runtime without modifying the app bundle."""

import argparse
import contextlib
import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from uuid import uuid4

BACKENDS = {
    "none": (),
    "stardist": ("stardist",),
    "cellpose": ("cellpose", "monai", "smp"),
    "both": ("stardist", "cellpose", "monai", "smp"),
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
        self.env.pop("EXHALE_NATIVE_INSTALLATION", None)

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
        elif "exhale" in arguments and getattr(self, "launch_token", None):
            env = dict(
                env,
                EXHALE_NATIVE_INSTALLATION=json.dumps(
                    {
                        "protocol": "1",
                        "kind": "macos",
                        "root": str(self.home.resolve()),
                        "token": self.launch_token,
                    }
                ),
            )
        subprocess.run(
            list(map(str, arguments)),
            env=env,
            cwd=self.home,
            check=True,
            stdout=getattr(self, "update_output", None),
            stderr=getattr(self, "update_output", None),
        )

    def install(self, selection, *, version=None, update_wheel=None):
        """Validate a fresh environment before switching the launch record to it."""
        self.root.mkdir(parents=True, exist_ok=True)
        environment = self.root / ("env-" + uuid4().hex)
        previous = self.state()
        wheel = (self.resources / self.config["wheel"]) if version is None else update_wheel
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
        suffix = "[" + ",".join(extras) + "]" if extras else ""
        requirement = str(wheel) + suffix if wheel else f"exhale-xrf{suffix}=={version}"
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
            if version is not None:
                self.run(
                    [
                        environment / "bin/python",
                        "-c",
                        "import sys; from importlib.metadata import version; "
                        "from packaging.version import Version; "
                        "assert Version(version('exhale-xrf')) == Version(sys.argv[1]), "
                        "'Installed version does not match requested update'",
                        version,
                    ]
                )
            self.run([environment / "bin/python", "-m", "exhale", "--startup-check"])
            installed = {
                "environment": environment.name,
                "wheel": self.config["wheel"],
                "backends": selection,
            }
            if version is not None:
                installed["version"] = version
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
                try:
                    shutil.rmtree(old)
                except OSError as error:
                    print(
                        f"Installed successfully; old runtime cleanup failed: {old}: {error}",
                        flush=True,
                    )
        print("Setup completed.", flush=True)

    def launch(self, arguments):
        request_path = self.home / "update-request.json"
        request_path.unlink(missing_ok=True)
        while True:
            state = self.state()
            if state is None or state["wheel"] != self.config["wheel"]:
                raise RuntimeError("Run EXHALE setup for this application version first.")
            self.launch_token = uuid4().hex
            self.run([self.root / state["environment"] / "bin/python", "-m", "exhale", *arguments])
            if not request_path.exists():
                return
            request = json.loads(request_path.read_text())
            request_path.unlink()
            if (
                request["token"] != self.launch_token
                or request["environment"] != state["environment"]
            ):
                raise ValueError(
                    "Update request does not belong to the application that just exited."
                )
            result = {"log": str(self.home / "update.log"), "success": False}
            with (self.home / "update.log").open("a", buffering=1) as log:
                self.update_output = log
                try:
                    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                        self.update(request["version"])
                    result["success"] = True
                except Exception:
                    traceback.print_exc(file=log)
                finally:
                    self.update_output = None
            (Path(request["job"]) / "result.json").write_text(json.dumps(result))
            arguments = []

    def update(self, version, wheel=None):
        """Preserve backend selection and activate only a validated requested release."""
        if not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", version):
            raise ValueError("Invalid update version.")
        state = self.state()
        if state is None:
            raise RuntimeError("No installed runtime to update.")
        self.install(state["backends"], version=version, update_wheel=wheel)

    def remove(self):
        if self.root.exists():
            shutil.rmtree(self.root)
        print("Private Python runtime removed. Projects and application settings were retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("action", choices=("install", "launch", "remove", "update"))
    parser.add_argument("--update-wheel", type=Path)
    parser.add_argument("--startup-check", action="store_true")
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    runtime = Runtime(args.resources, args.home)
    with runtime.locked():
        if args.action == "install":
            if len(args.arguments) != 1 or args.arguments[0] not in BACKENDS:
                parser.error("install requires none, stardist, cellpose, or both")
            runtime.install(args.arguments[0])
        elif args.action == "launch":
            runtime.launch(args.arguments + (["--startup-check"] if args.startup_check else []))
        elif args.action == "update":
            if len(args.arguments) != 1:
                parser.error("update requires a version")
            runtime.update(args.arguments[0], args.update_wheel)
        else:
            runtime.remove()


if __name__ == "__main__":
    main()
