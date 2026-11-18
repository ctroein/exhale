"""Measure Windows runtime selections without starting Exhale or its backends."""

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

EXTRAS = {
    "none": "",
    "stardist": "[stardist]",
    "cellpose": "[cellpose,monai,smp]",
    "both": "[stardist,cellpose,monai,smp]",
}


def directory_size(directory):
    """Sum file lengths without following directory junctions or symlinks."""
    total = 0
    for root, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if not Path(root, name).is_symlink()]
        total += sum(Path(root, name).stat().st_size for name in files)
    return total


def measure_runtime(root, environment):
    """Reserve runtime space plus a full cache copy and ten percent working margin."""
    python_bytes = directory_size(root / "runtime/python")
    environment_bytes = directory_size(environment)
    unit = 100 * 1024 * 1024
    extra_bytes = math.ceil((python_bytes + 2 * environment_bytes) * 1.1 / unit) * unit
    return {
        "python_bytes": python_bytes,
        "environment_bytes": environment_bytes,
        "extra_bytes": extra_bytes,
    }


def main():
    """Install each dependency selection locally or measure an existing CI installation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("measure on Windows")
    report = {
        "measured": str(date.today()),
        "platform": "Windows x64, Python 3.11",
        "reserve": "One environment-sized cache copy plus 10%, rounded up to 100 MiB",
        "selections": {},
    }
    if args.installed_root:
        root = args.installed_root.resolve()
        state = json.loads((root / "runtime/installed.json").read_text(encoding="utf-8-sig"))
        report["wheel"] = state["wheel"]
        report["selections"][state["backends"]] = measure_runtime(
            root, root / "runtime" / state["environment"]
        )
    else:
        if not all((args.uv, args.wheel, args.work)):
            parser.error("provide --installed-root or --uv, --wheel and --work")
        root = args.work.resolve()
        report["wheel"] = args.wheel.name
        env = dict(os.environ)
        env.update(
            UV_PYTHON_INSTALL_DIR=str(root / "runtime/python"),
            UV_PYTHON_BIN_DIR=str(root / "runtime/bin"),
            UV_CACHE_DIR=str(root / "runtime/cache"),
            UV_PYTHON_PREFERENCE="only-managed",
            UV_NO_CONFIG="1",
        )
        requirements = Path(__file__).resolve().parents[2] / "requirements-cellpose.txt"
        for selection, extras in EXTRAS.items():
            environment = root / "runtime" / f"env-{selection}"
            if environment.exists():
                parser.error(f"measurement environment already exists: {environment}")
            print(f"Measuring {selection}", flush=True)
            subprocess.run(
                [str(args.uv), "venv", "--python", "3.11", str(environment)],
                check=True,
                env=env,
            )
            command = [
                str(args.uv),
                "pip",
                "install",
                "--python",
                str(environment / "Scripts/python.exe"),
                "--prerelease",
                "disallow",
                str(args.wheel.resolve()) + extras,
            ]
            if selection in ("cellpose", "both"):
                command += ["-r", str(requirements)]
            subprocess.run(command, check=True, env=env)
            report["selections"][selection] = measure_runtime(root, environment)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report["selections"][selection]), flush=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
