#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 13 21:19:42 2026

@author: carl

Builds Windows installer using pyinstaller and Inno Setup.
"""
from pathlib import Path
import subprocess
import sys
import os

from exhale.appversion import exhale_version

APP_NAME = "exhale"
PLATFORM = "win"
DIST_DIR = Path("dist") / APP_NAME
ZIP_BASE = Path("dist") / f"{APP_NAME}-{exhale_version}-{PLATFORM}"
INNO_SCRIPT = Path("recipe") / "exhale.iss"
INNO_EXE = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"

def run(cmd):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)

def main():
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "recipe/exhale.spec"])

    do_zip = False
    if do_zip:
        import shutil
        zip_path = ZIP_BASE.with_suffix(ZIP_BASE.suffix + ".zip")
        if zip_path.exists():
            zip_path.unlink()
        shutil.make_archive(str(ZIP_BASE), "zip", root_dir=DIST_DIR.parent,
             base_dir=DIST_DIR.name)
        print("Created", zip_path)

    # Inno Setup
    run([
        INNO_EXE,
        f"/DMyAppVersion={exhale_version}",
        str(INNO_SCRIPT),
    ])

if __name__ == "__main__":
    main()

