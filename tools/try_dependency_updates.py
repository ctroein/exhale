#!/usr/bin/env python3
"""Create a Linux dependency trial, run checks, and launch the source checkout."""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def trial_requirements(project, exceptions, backends=("stardist", "cellpose", "monai")):
    """Remove project version bounds except explicitly documented exceptions."""
    retained = {canonicalize_name(name): reason for name, reason in exceptions.items()}
    requirements = []
    selected = list(project["dependencies"])
    for backend in backends:
        selected.extend(project["optional-dependencies"][backend])
    for text in selected:
        requirement = Requirement(text)
        name = canonicalize_name(requirement.name)
        if name in retained:
            if not retained[name].strip():
                raise ValueError(f"Missing reason for retaining {name}")
        elif not requirement.url:
            requirement.specifier = type(requirement.specifier)()
        requirements.append(str(requirement))
    return requirements


def main():
    """Prepare a fresh trial or rerun checks against an existing one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, help="reuse an existing trial environment")
    parser.add_argument(
        "--no-gui", action="store_true", help="run checks without launching the GUI"
    )
    parser.add_argument(
        "--backends",
        choices=("none", "stardist", "cellpose", "monai", "both"),
        default="both",
        help="backends for a new trial (default: both); ignored when reusing an environment",
    )
    args = parser.parse_args()
    backends = {
        "none": (),
        "stardist": ("stardist",),
        "cellpose": ("cellpose", "monai"),
        "monai": ("monai",),
        "both": ("stardist", "cellpose", "monai"),
    }[args.backends]
    if not sys.platform.startswith("linux"):
        parser.error("dependency trials currently target Linux")
    if not shutil.which("uv"):
        parser.error("uv must be installed and available on PATH")
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    policy = config["tool"]["dependency-trial"]
    environment = args.environment
    if environment is None:
        environment = ROOT / ".dependency-trials" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        requirements = trial_requirements(config["project"], policy["keep"], backends)
        environment.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        (environment / "requirements.txt").write_text("\n".join(requirements) + "\n")
        python = environment / "bin" / "python"
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--upgrade",
                "--prerelease",
                "disallow",
                "-r",
                str(environment / "requirements.txt"),
                *(
                    ["-r", str(ROOT / "requirements-cellpose.txt")]
                    if "cellpose" in backends
                    else []
                ),
                "pytest",
                "ruff",
            ],
            check=True,
        )
    environment = environment.resolve()
    python = environment / "bin" / "python"
    print(f"Trial environment: {environment}", flush=True)
    print(
        f"Reuse: {sys.executable} tools/try_dependency_updates.py --environment {environment}",
        flush=True,
    )
    with (environment / "installed.txt").open("w") as output:
        subprocess.run(["uv", "pip", "freeze", "--python", str(python)], stdout=output, check=True)
    env = os.environ.copy()
    env.setdefault("QT_API", "pyqt6")
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONUNBUFFERED"] = "1"
    checks_env = dict(env, QT_QPA_PLATFORM="offscreen")
    commands = (
        ["-m", "ruff", "format", "--check", "."],
        ["-m", "ruff", "check", "."],
        ["run_exhale.py", "--help"],
        ["run_exhale.py", "--startup-check"],
        ["-m", "pytest"],
    )
    for command in commands:
        print(f"Running: {python} {' '.join(command)}", flush=True)
        subprocess.run([str(python), *command], cwd=ROOT, env=checks_env, check=True)
    if not args.no_gui:
        print("Checks passed; launching EXHALE for manual testing.", flush=True)
        subprocess.run([str(python), "run_exhale.py"], cwd=ROOT, env=env, check=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
