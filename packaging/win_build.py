#!/usr/bin/env python3
"""Build the Windows uv payload, native launcher and Inno Setup installer."""

import argparse
import ast
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


def model_metadata():
    """Read model IDs and download sizes without importing the application."""
    tree = ast.parse((ROOT / "exhale/analysis/model_store.py").read_text(encoding="utf-8"))
    models = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "TrainedModel"
        ):
            models[node.targets[0].id] = {
                keyword.arg: ast.literal_eval(keyword.value) for keyword in node.value.keywords
            }
    return models


def space_definitions(models, payload_bytes):
    """Convert measured runtime footprints into additive Inno component estimates."""
    data = json.loads((ROOT / "packaging/windows/space-estimates.json").read_text())
    sizes = data["selections"]
    core = sizes["none"]["extra_bytes"]
    star = max(0, sizes["stardist"]["extra_bytes"] - core)
    pytorch = max(
        0,
        sizes["cellpose"]["extra_bytes"] - core,
        sizes["both"]["extra_bytes"] - sizes["stardist"]["extra_bytes"],
    )
    values = {"SpaceCore": core, "SpaceStarDist": star, "SpacePyTorch": pytorch}
    for selection, label in (
        ("none", "None"),
        ("stardist", "StarDist"),
        ("cellpose", "PyTorch"),
        ("both", "Both"),
    ):
        values["Runtime" + label] = (
            sizes[selection]["python_bytes"] + sizes[selection]["environment_bytes"] + payload_bytes
        )
    values["ModelsStarDist"] = models["STARDIST_MODEL"]["size"]
    values["ModelsPyTorch"] = sum(
        models[name]["size"] for name in ("CELLPOSE_MODEL", "MONAI_MODEL", "SMP_MODEL")
    )
    return "".join(f"#define {name} {value}\n" for name, value in values.items())


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
    if metadata["Name"] != "exhale-xrf":
        parser.error("--wheel must contain exhale-xrf")
    version = metadata["Version"]
    payload = ROOT / "dist/windows-payload"
    if payload.exists():
        parser.error(f"payload already exists; use a clean build directory: {payload}")
    payload.mkdir(parents=True)
    shutil.copy2(wheel, payload / wheel.name)
    shutil.copy2(ROOT / "requirements-cellpose.txt", payload / "requirements-cellpose.txt")
    shutil.copy2(ROOT / "LICENSE", payload / "LICENSE.txt")
    models = model_metadata()
    (payload / "setup.json").write_text(
        json.dumps(
            {"wheel": wheel.name, "model_ids": ";".join(m["model_id"] for m in models.values())}
        )
    )
    assembly_info = payload / "LauncherVersion.cs"
    assembly_info.write_text(
        "[assembly: System.Reflection.AssemblyInformationalVersion(" + json.dumps(version) + ")]\n"
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
            "/reference:System.Drawing.dll",
            "/reference:System.Web.Extensions.dll",
            f"/win32icon:{ROOT / 'packaging/icons/xrf.ico'}",
            f"/out:{payload / 'exhale.exe'}",
            str(ROOT / "packaging/windows/Launcher.cs"),
            str(assembly_info),
        ],
        check=True,
    )
    subprocess.run([str(payload / "exhale.exe"), "--self-test"], check=True)
    assembly_info.unlink()
    payload_bytes = sum(path.stat().st_size for path in payload.iterdir() if path.is_file())
    (payload / "release.iss").write_text(
        f'#define MyAppVersion "{version}"\n#define WheelFile "{wheel.name}"\n'
        + space_definitions(models, payload_bytes)
    )
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
