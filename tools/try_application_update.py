#!/usr/bin/env python3
"""Exercise a Linux application update using two local wheels and an isolated uv tool."""

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import tomllib

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("9999.0.0+local1", "9999.0.1+local2")


class TrialIndex(ThreadingHTTPServer):
    """Serve only the test wheels and release metadata on the loopback interface."""

    def __init__(self, wheels):
        self.wheels = wheels
        self.offer_update = False
        self.hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels}
        super().__init__(("127.0.0.1", 0), TrialRequest)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def visible_wheels(self):
        return self.wheels if self.offer_update else self.wheels[:1]


class TrialRequest(BaseHTTPRequestHandler):
    """Provide a minimal simple package index; other packages fall back to PyPI."""

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        index = self.server
        if path == "/simple/exhale-xrf/":
            links = "\n".join(
                f'<a href="/wheels/{html.escape(p.name)}#sha256={index.hashes[p.name]}">'
                f"{html.escape(p.name)}</a>"
                for p in index.visible_wheels
            )
            self._send("text/html", f"<!doctype html><html><body>{links}</body></html>".encode())
        elif path == "/pypi/exhale-xrf/json":
            releases = {
                version: [{"requires_python": ">=3.11,<3.14", "yanked": False}]
                for version, _wheel in zip(VERSIONS, index.visible_wheels, strict=False)
            }
            self._send("application/json", json.dumps({"releases": releases}).encode())
        else:
            wheel = next((p for p in index.visible_wheels if path == f"/wheels/{p.name}"), None)
            if wheel:
                self._send("application/octet-stream", wheel.read_bytes())
            else:
                self.send_error(404)

    def _send(self, content_type, body):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        # uv must see the second wheel immediately after the first install finishes.
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, *_args):
        pass


def build_wheels(directory, uv):
    """Build a snapshot twice with temporary SCM versions, leaving the checkout alone."""
    source = directory / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(
        ROOT / "exhale", source / "exhale", ignore=shutil.ignore_patterns("__pycache__")
    )
    wheels = []
    for version in VERSIONS:
        environment = os.environ.copy()
        environment["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_EXHALE_XRF"] = version
        subprocess.run(
            [
                uv,
                "build",
                "--python",
                sys.executable,
                "--wheel",
                "--out-dir",
                str(directory / "wheels"),
                str(source),
            ],
            check=True,
            env=environment,
        )
        wheels.append(directory / "wheels" / f"exhale_xrf-{version}-py3-none-any.whl")
        if not wheels[-1].is_file():
            raise RuntimeError(f"Build did not produce the expected wheel: {wheels[-1]}")
    return wheels


def trial_environment(directory, url):
    """Isolate uv tools and application preferences while reusing uv's dependency cache."""
    environment = os.environ.copy()
    environment.update(
        UV_TOOL_DIR=str(directory / "tools"),
        UV_TOOL_BIN_DIR=str(directory / "bin"),
        UV_NO_CONFIG="1",
        XDG_CONFIG_HOME=str(directory / "config"),
        XDG_DATA_HOME=str(directory / "data"),
        EXHALE_UPDATE_TEST_URL=f"{url}/pypi/exhale-xrf/json",
    )
    # Retain XDG_CACHE_HOME and UV_CACHE_DIR so dependency downloads are reusable.
    return environment


def main():
    """Install the first test release, expose the second, and keep its server running."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="new trial directory (must not exist)")
    parser.add_argument(
        "--extra",
        action="append",
        choices=tuple(project["optional-dependencies"]),
        default=[],
        help="include a segmentation extra; repeat for several (default: none)",
    )
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("application update trials currently support Linux")
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv must be available on PATH")
    directory = (
        args.directory or ROOT / ".update-trials" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    ).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    print(f"Trial directory: {directory}", flush=True)
    wheels = build_wheels(directory, uv)
    with TrialIndex(wheels) as index:
        thread = threading.Thread(target=index.serve_forever, daemon=True)
        thread.start()
        try:
            environment = trial_environment(directory, index.url)
            requirement = "exhale-xrf"
            if args.extra:
                requirement += "[" + ",".join(sorted(set(args.extra))) + "]"
            command = [
                uv,
                "tool",
                "install",
                "--python",
                sys.executable,
                "--index",
                f"{index.url}/simple",
                requirement,
            ]
            if "cellpose" in args.extra:
                command.extend(["--with-requirements", str(ROOT / "requirements-cellpose.txt")])
            subprocess.run(command, check=True, env=environment)
            index.offer_update = True
            launcher = directory / "bin/exhale"
            with (directory / "application.log").open("ab") as log:
                subprocess.Popen(
                    [str(launcher)],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=directory,
                    start_new_session=True,
                )
            print(
                f"\nTrial directory: {directory}\n"
                f"Installed {VERSIONS[0]}; offering {VERSIONS[1]}.\n"
                "In Exhale, use Settings → Check now → Update now.\n"
                "You can test cancelling the quit, then check again to apply the update.\n"
                "Keep this terminal open through the update and restart.\n"
                "When finished, close the trial Exhale and press Ctrl+C here.\n"
                "The trial and logs are retained; delete its directory afterwards.\n",
                flush=True,
            )
            thread.join()
        except KeyboardInterrupt:
            print(f"\nStopped test server. Trial retained at {directory}", flush=True)
        finally:
            index.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
