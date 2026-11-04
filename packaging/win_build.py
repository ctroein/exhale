#!/usr/bin/env python3
"""Build the Windows uv payload, native launcher and Inno Setup installer."""

import argparse
import email
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
UV_VERSION = "0.13.7"


def download_uv(destination):
    """Verify the pinned upstream archive before extracting its Windows executable."""
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read()
    with urllib.request.urlopen(url + ".sha256", timeout=120) as response:
        expected = response.read().decode().split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("uv archive checksum mismatch")
    with ZipFile(io.BytesIO(archive)) as handle:
        executable = next(name for name in handle.namelist() if Path(name).name == "uv.exe")
        destination.write_bytes(handle.read(executable))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--iscc", help="path to Inno Setup's ISCC.exe")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("build on Windows with .NET Framework and Inno Setup installed")
    wheel = args.wheel.resolve()
    with ZipFile(wheel) as archive:
        name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(name))
    if metadata["Name"] != "exhale-lung":
        parser.error("--wheel must contain exhale-lung")
    version = metadata["Version"]
    payload = ROOT / "dist/windows-payload"
    if payload.exists():
        parser.error(f"payload already exists; use a clean build directory: {payload}")
    payload.mkdir(parents=True)
    shutil.copy2(wheel, payload / wheel.name)
    shutil.copy2(ROOT / "requirements-cellpose.txt", payload / "requirements-cellpose.txt")
    shutil.copy2(ROOT / "LICENSE", payload / "LICENSE.txt")
    (payload / "setup.json").write_text(json.dumps({"wheel": wheel.name}))
    (payload / "release.iss").write_text(
        f'#define MyAppVersion "{version}"\n#define WheelFile "{wheel.name}"\n'
    )
    download_uv(payload / "uv.exe")
    with urllib.request.urlopen(
        f"https://raw.githubusercontent.com/astral-sh/uv/{UV_VERSION}/LICENSE-MIT", timeout=30
    ) as response:
        (payload / "uv-LICENSE-MIT.txt").write_bytes(response.read())
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:x64",
            "/reference:System.Windows.Forms.dll",
            "/reference:System.Web.Extensions.dll",
            f"/win32icon:{ROOT / 'packaging/icons/xrf.ico'}",
            f"/out:{payload / 'exhale.exe'}",
            str(ROOT / "packaging/windows/Launcher.cs"),
        ],
        check=True,
    )
    subprocess.run([str(payload / "exhale.exe"), "--self-test"], check=True)
    iscc = args.iscc or shutil.which("iscc")
    if not iscc:
        candidate = Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6/ISCC.exe"
        if candidate.is_file():
            iscc = str(candidate)
    if not iscc:
        parser.error("ISCC.exe not found; pass --iscc")
    subprocess.run([iscc, str(ROOT / "packaging/exhale.iss")], check=True)
    print(f"Installer: {ROOT / 'dist' / ('exhale-' + version + '-setup.exe')}")


if __name__ == "__main__":
    main()
