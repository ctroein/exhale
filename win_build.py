#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Apr 13 21:19:42 2026

@author: carl
"""
from pathlib import Path
import shutil
import subprocess
import sys

from exhale.appversion import exhale_version

APP_NAME = "exhale"
PLATFORM = "win"
DIST_DIR = Path("dist") / APP_NAME
ZIP_BASE = Path("dist") / f"{APP_NAME}-{exhale_version}-{PLATFORM}"
INNO_SCRIPT = Path("recipe") / "exhale.iss"
NSIS_SCRIPT = Path("recipe") / "exhale.nsi"

def run(cmd):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)

def main():
    run([sys.executable, "-m", "PyInstaller", "--clean", "recipe/exhale.spec"])

    zip_path = ZIP_BASE.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(ZIP_BASE), "zip",
                        root_dir=DIST_DIR.parent,
                        base_dir=DIST_DIR.name)
    print("Created", zip_path)

    # Inno Setup
    if INNO_SCRIPT.exists():
        run([
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            f"/DMyAppVersion={exhale_version}",
            str(INNO_SCRIPT),
        ])

    # NSIS alternative
    # if NSIS_SCRIPT.exists():
    #     run([
    #         r"C:\Program Files (x86)\NSIS\makensis.exe",
    #         f"/DVERSION={exhale_version}",
    #         str(NSIS_SCRIPT),
    #     ])

if __name__ == "__main__":
    main()

