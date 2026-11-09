#!/usr/bin/env python3
"""Check native runtime updates between local wheels and failed-update recovery in CI."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Keep native launcher identity and selected backends across checked updates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    resources = (
        args.launcher.parent
        if sys.platform == "win32"
        else args.launcher.parent.parent / "Resources"
    )
    uv = resources / ("uv.exe" if sys.platform == "win32" else "uv")
    state_path = args.home / "runtime/installed.json"
    before = json.loads(state_path.read_text(encoding="utf-8-sig"))

    def backend_modules(state):
        python = (
            args.home
            / "runtime"
            / state["environment"]
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        code = (
            "import importlib.util, json; print(json.dumps({name: "
            "importlib.util.find_spec(name) is not None "
            "for name in ('tensorflow', 'stardist', 'torch', 'cellpose', 'monai', 'segmentation_models_pytorch', 'dinov3')}))"
        )
        result = subprocess.run(
            [str(python), "-c", code], check=True, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    before_modules = backend_modules(before)
    environment = dict(os.environ, EXHALE_SETUP_HOME=str(args.home))
    spec = importlib.util.spec_from_file_location(
        "update_trial", ROOT / "tools/try_application_update.py"
    )
    trial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trial)

    def run(arguments, name, *, success=True):
        with (args.logs / f"{name}.log").open("wb") as log:
            result = subprocess.run(
                [str(args.launcher), *map(str, arguments)],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if (result.returncode == 0) != success:
            raise RuntimeError(f"Unexpected exit {result.returncode} for {name}; see {args.logs}")

    try:
        with tempfile.TemporaryDirectory(prefix="exhale-native-update-") as temporary:
            wheels = trial.build_wheels(Path(temporary), str(uv))
            for version, wheel in zip(trial.VERSIONS, wheels, strict=True):
                run(["--update-runtime", version, "--update-wheel", wheel], f"update-{version}")
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
                assert state["version"] == version
                assert state["backends"] == before["backends"]
                assert state["wheel"] == before["wheel"], "Update changed installer identity"
                assert backend_modules(state) == before_modules, "Update changed installed backends"
                assert len(list((args.home / "runtime").glob("env-*"))) == 1
                run(["--startup-check"], f"startup-{version}")
            saved = state_path.read_bytes()
            # Force validation failure after installation, rather than only testing a missing file.
            run(
                ["--update-runtime", "9999.0.2+invalid", "--update-wheel", wheels[-1]],
                "rejected-update",
                success=False,
            )
            assert state_path.read_bytes() == saved, "Failed update changed installed.json"
            assert len(list((args.home / "runtime").glob("env-*"))) == 1
            run(["--startup-check"], "startup-after-rejected-update")
        print(
            "Native updates preserved backends, launched both versions, and recovered from failure."
        )
    finally:
        for name in ("runtime.log", "update.log"):
            path = args.home / name
            if path.exists():
                shutil.copyfile(path, args.logs / f"updates-{name}")
        if state_path.exists():
            shutil.copyfile(state_path, args.logs / "updates-installed.json")


if __name__ == "__main__":
    main()
