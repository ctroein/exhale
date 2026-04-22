#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builds Windows installer using PyInstaller and Inno Setup.
"""
from pathlib import Path
import os
import subprocess
import sys

# packaging/ -> project root
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Make sure imports work when running this file directly from packaging/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def get_version():
    tag = subprocess.check_output(
        ["git", "describe", "--tags", "--abbrev=0"],
        text=True,
    ).strip()
    return tag.lstrip("v")

APP_NAME = "exhale"
PLATFORM = "win"
version = get_version()

DIST_DIR = ROOT / "dist" / APP_NAME
ZIP_BASE = ROOT / "dist" / f"{APP_NAME}-{version}-{PLATFORM}"

SPEC_FILE = HERE / "exhale.spec"
INNO_SCRIPT = HERE / "exhale.iss"
INNO_EXE = (Path(os.environ["LOCALAPPDATA"]) /
            "Programs" / "Inno Setup 6" / "ISCC.exe")

def run(cmd, cwd=None):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, cwd=cwd)

def main():
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
         str(SPEC_FILE)], cwd=HERE)

    do_zip = False
    if do_zip:
        import shutil
        zip_path = ZIP_BASE.with_suffix(ZIP_BASE.suffix + ".zip")
        if zip_path.exists():
            zip_path.unlink()
        shutil.make_archive(
            str(ZIP_BASE),
            "zip",
            root_dir=DIST_DIR.parent,
            base_dir=DIST_DIR.name,
        )
        print("Created", zip_path)

    run([str(INNO_EXE), f"/DMyAppVersion={version}", str(INNO_SCRIPT)], cwd=HERE)

if __name__ == "__main__":
    main()
