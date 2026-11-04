#!/usr/bin/env python3
"""Build the native macOS setup app and DMG around a wheel and pinned uv binary."""

import argparse
import email
import hashlib
import io
import json
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
UV_VERSION = "0.13.7"


def download_uv(architecture, destination):
    """Verify the upstream archive checksum and extract only the uv executable."""
    target = {"arm64": "aarch64", "x86_64": "x86_64"}[architecture]
    basename = f"uv-{target}-apple-darwin.tar.gz"
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{basename}"
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read()
    with urllib.request.urlopen(url + ".sha256", timeout=120) as response:
        expected = response.read().decode().split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("uv archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as handle:
        member = handle.getmember(f"uv-{target}-apple-darwin/uv")
        if not member.isfile():
            raise ValueError("uv archive does not contain a regular executable")
        with handle.extractfile(member) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
    destination.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--version", help="display version; defaults to the wheel metadata")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("build on macOS with Xcode command line tools installed")
    architecture = platform.machine()
    if architecture not in ("arm64", "x86_64"):
        parser.error(f"unsupported architecture: {architecture}")
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("--wheel must be an existing EXHALE wheel")
    args.output.mkdir(parents=True, exist_ok=True)
    app = args.output / "EXHALE.app"
    if app.exists():
        parser.error(f"output already exists: {app}")
    resources = app / "Contents/Resources"
    executable = app / "Contents/MacOS/EXHALE"
    resources.mkdir(parents=True)
    executable.parent.mkdir()
    shutil.copy2(wheel, resources / wheel.name)
    for name in ("requirements-cellpose.txt",):
        shutil.copy2(ROOT / name, resources / name)
    shutil.copy2(ROOT / "packaging/macos/runtime.py", resources / "runtime.py")
    shutil.copy2(ROOT / "packaging/icons/xrf.icns", resources / "xrf.icns")
    (resources / "setup.json").write_text(
        json.dumps({"wheel": wheel.name, "architecture": architecture})
    )
    with ZipFile(wheel) as archive:
        metadata_file = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = email.message_from_bytes(archive.read(metadata_file))
    if metadata["Name"] != "exhale-xrf":
        parser.error("wheel must contain exhale-xrf")
    version = (args.version or metadata["Version"]).removeprefix("v")
    bundle_version = re.match(r"\d+(?:\.\d+){0,2}", version)
    if bundle_version is None:
        parser.error("version must start with a numeric release version")
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleExecutable": "EXHALE",
                "CFBundleIdentifier": "io.github.ctroein.Exhale",
                "CFBundleName": "EXHALE",
                "CFBundleDisplayName": "EXHALE",
                "CFBundlePackageType": "APPL",
                "CFBundleIconFile": "xrf.icns",
                "CFBundleShortVersionString": bundle_version.group(),
                "CFBundleVersion": bundle_version.group(),
                "LSMinimumSystemVersion": "13.0",
                "NSHighResolutionCapable": True,
            },
            stream,
        )
    download_uv(architecture, resources / "uv")
    licenses = resources / "licenses"
    licenses.mkdir()
    with urllib.request.urlopen(
        f"https://raw.githubusercontent.com/astral-sh/uv/{UV_VERSION}/LICENSE-MIT", timeout=30
    ) as response:
        (licenses / "uv-LICENSE-MIT").write_bytes(response.read())
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-target",
            f"{architecture}-apple-macosx13.0",
            "-framework",
            "AppKit",
            str(ROOT / "packaging/macos/Launcher.swift"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    # Ad-hoc signing supports local execution, but supplies no verified Developer ID.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    staging = args.output / f"dmg-{architecture}"
    staging.mkdir()
    shutil.copytree(app, staging / app.name)
    (staging / "Applications").symlink_to("/Applications")
    shutil.copy2(ROOT / "packaging/macos/INSTALL.txt", staging / "INSTALL.txt")
    dmg = args.output / f"exhale-macos-{architecture}.dmg"
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "EXHALE",
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(dmg),
        ],
        check=True,
    )
    print(dmg)


if __name__ == "__main__":
    main()
