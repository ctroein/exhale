"""Windows installer payload integrity and wheel-to-installer metadata."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

_spec = importlib.util.spec_from_file_location(
    "windows_build", Path(__file__).resolve().parents[1] / "packaging/win_build.py"
)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def archive_bytes():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("uv.exe", b"native uv executable")
        archive.writestr("ignored.txt", "not executable")
    return stream.getvalue()


@pytest.mark.parametrize("valid", [True, False])
def test_uv_download_is_verified_before_use(tmp_path, monkeypatch, valid):
    archive = archive_bytes()
    digest = hashlib.sha256(archive).hexdigest() if valid else "0" * 64
    monkeypatch.setattr(
        builder.urllib.request,
        "urlopen",
        lambda url, **_kwargs: io.BytesIO(digest.encode() if url.endswith(".sha256") else archive),
    )
    target = tmp_path / "uv.exe"
    if valid:
        builder.download_uv(target)
        assert target.read_bytes() == b"native uv executable"
    else:
        with pytest.raises(ValueError, match="checksum"):
            builder.download_uv(target)
        assert not target.exists()


def test_builder_uses_local_wheel_and_compiles_native_launcher(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "requirements-cellpose.txt").write_text("pinned DINOv3")
    (root / "LICENSE").write_text("MIT")
    wheel = tmp_path / "exhale_xrf-1.2.3-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "exhale_xrf-1.2.3.dist-info/METADATA", "Name: exhale-xrf\nVersion: 1.2.3\n"
        )
    monkeypatch.setattr(builder, "ROOT", root)
    monkeypatch.setattr(builder.sys, "platform", "win32")
    monkeypatch.setattr(builder.sys, "argv", ["build", "--wheel", str(wheel), "--iscc", "ISCC.exe"])
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    monkeypatch.setattr(builder, "download_uv", lambda path: path.write_bytes(b"uv"))
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", lambda *_a, **_kw: io.BytesIO(b"uv license")
    )
    commands = []
    monkeypatch.setattr(builder.subprocess, "run", lambda command, **_kw: commands.append(command))
    builder.main()
    payload = root / "dist/windows-payload"
    assert json.loads((payload / "setup.json").read_text()) == {"wheel": wheel.name}
    assert (payload / wheel.name).read_bytes() == wheel.read_bytes()
    assert (payload / "requirements-cellpose.txt").read_text() == "pinned DINOv3"
    assert '#define MyAppVersion "1.2.3"' in (payload / "release.iss").read_text()
    assert any("/target:winexe" in command for command in commands)
    assert commands[-2] == [str(payload / "exhale.exe"), "--self-test"]
    assert commands[-1] == ["ISCC.exe", str(root / "packaging/exhale.iss")]
