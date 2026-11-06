"""Linux uv-tool identification, release checks, and detached update execution.

The copied helper runs with the base Python and only needs the standard library.
It waits for the application process to exit before asking uv to replace packages.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.request
from pathlib import Path

import tomllib

PACKAGE = "exhale-xrf"
AUTOMATIC_CHECKS_KEY = "updates/automatic_checks"
LAST_CHECK_KEY = "updates/last_check"
NOTIFIED_VERSION_KEY = "updates/notified_version"
CHECK_INTERVAL = 24 * 60 * 60
UPDATE_COMMAND = f"uv tool upgrade {PACKAGE}"
# Keep pipe writers open until process exit, including while Python tears down Qt.
_exit_pipes = []
_application_locks = []


def hold_application_lock():
    """Keep recognised tool instances from being updated while still running."""
    try:
        installation = tool_installation()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        return
    stream = installation_lock(installation, exclusive=False)
    _application_locks.append(stream)


def installation_lock(installation, *, exclusive):
    """Lock outside the replaceable environment without blocking another process."""
    import fcntl

    path = Path(installation["prefix"]).parent / ".exhale-xrf-update.lock"
    stream = path.open("a+b")
    try:
        fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError(
            "Another Exhale instance or update is running. Close it and try again."
        ) from None
    return stream


def tool_installation(prefix=None, package_directory=None, uv=None):
    """Identify this exact uv tool environment; reject source and unrelated installs."""
    if not sys.platform.startswith("linux"):
        raise ValueError("In-application updates currently support Linux uv tool installations.")
    prefix = Path(prefix or sys.prefix).resolve()
    package_directory = Path(package_directory or Path(__file__).parent).resolve()
    if not package_directory.is_relative_to(prefix):
        raise ValueError("This is a source checkout. Update it through Git.")
    uv = uv or shutil.which("uv")
    if not uv:
        raise ValueError("uv was not found on PATH. Update using your installation method.")
    result = subprocess.run(
        [uv, "tool", "dir"], check=True, capture_output=True, text=True, timeout=5
    )
    tools = Path(result.stdout.strip()).resolve()
    if prefix != tools / PACKAGE:
        raise ValueError("This environment is not the exhale-xrf tool managed by this uv.")
    receipt = prefix / "uv-receipt.toml"
    with receipt.open("rb") as stream:
        tool = tomllib.load(stream)["tool"]
    if not isinstance(tool, dict):
        raise ValueError("The uv tool receipt is not recognised.")
    requirements = tool.get("requirements", [])
    requirement = next(
        (r for r in requirements if isinstance(r, dict) and r.get("name") == PACKAGE), None
    )
    if requirement is None or not set(requirement).issubset(
        {"name", "extras", "specifier", "marker", "index"}
    ):
        raise ValueError("This uv tool was not installed from a package-index requirement.")
    entrypoints = tool.get("entrypoints", [])
    entrypoint = next(
        (e for e in entrypoints if isinstance(e, dict) and e.get("name") == "exhale"), None
    )
    if entrypoint is None:
        raise ValueError("The uv receipt has no Exhale launcher.")
    launcher = Path(entrypoint["install-path"])
    if not launcher.is_absolute() or not launcher.is_file():
        raise ValueError("The registered Exhale launcher is missing.")
    # Reject another user's installation even if a shared group grants write access.
    paths = (tools, prefix, receipt, launcher.parent, launcher)
    if any(p.stat().st_uid != os.getuid() or not os.access(p, os.W_OK) for p in paths):
        raise ValueError("The uv installation is not owned and writable by the current user.")
    return {
        "uv": str(Path(uv).absolute()),
        "prefix": str(prefix),
        "launcher": str(launcher),
        "receipt": receipt.read_text(encoding="utf-8"),
    }


def latest_release(data, current, python_version=None):
    """Select a newer stable, non-yanked release supporting this Python version."""
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    installed = Version(current)
    python_version = python_version or ".".join(map(str, sys.version_info[:3]))
    candidates = []
    for number, files in data.get("releases", {}).items():
        try:
            version = Version(number)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease or version <= installed:
            continue
        if any(
            not file.get("yanked", False)
            and SpecifierSet(file.get("requires_python") or "").contains(python_version)
            for file in files
        ):
            candidates.append(version)
    return str(max(candidates)) if candidates else None


def check_release(current):
    """Fetch public PyPI release metadata with a bounded timeout and response size."""
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{PACKAGE}/json",
        headers={"User-Agent": f"Exhale/{current} update-check", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("The package index response is too large.")
    return latest_release(json.loads(payload), current)


def prepare_update(installation, state_directory):
    """Copy the standalone helper outside the environment which will be replaced."""
    directory = Path(state_directory)
    directory.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="update-", dir=directory))
    shutil.copyfile(__file__, job / "helper.py")
    (job / "plan.json").write_text(json.dumps(installation), encoding="utf-8")
    return job


def launch_update(job):
    """Start an isolated helper; the pipe gates mutation on this process exiting."""
    read_fd, write_fd = os.pipe()
    try:
        with (job / "update.log").open("ab") as log:
            subprocess.Popen(
                [sys._base_executable, "-I", str(job / "helper.py"), str(job), str(read_fd)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                pass_fds=(read_fd,),
                start_new_session=True,
                cwd=job,
            )
    except Exception:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    _exit_pipes.append(write_fd)


def run_update(job):
    """Revalidate ownership and receipt, upgrade through uv, and check startup."""
    plan = json.loads((job / "plan.json").read_text(encoding="utf-8"))
    prefix = Path(plan["prefix"])
    installation = tool_installation(prefix, prefix / "lib", plan["uv"])
    if any(plan.get(key) != value for key, value in installation.items()):
        raise ValueError("The uv installation changed after the update was requested. Check again.")
    with installation_lock(installation, exclusive=True):
        _upgrade(plan)


def _upgrade(plan):
    """Let uv retain its recorded requirements, then validate the installed release."""
    prefix = Path(plan["prefix"])
    command = [plan["uv"], "tool", "upgrade", PACKAGE]
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)
    version_check = subprocess.run(
        [
            str(prefix / "bin/python"),
            "-c",
            "import sys; from importlib.metadata import version; "
            "from packaging.version import Version; "
            "sys.exit(0 if Version(version('exhale-xrf')) >= Version(sys.argv[1]) else 1)",
            plan["version"],
        ],
    )
    if version_check.returncode:
        raise RuntimeError(
            "uv did not install the offered release. The original installation constraints "
            "or dependency compatibility may prevent this upgrade; see uv's output above."
        )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.run([plan["launcher"], "--startup-check"], check=True, env=environment, timeout=180)


def helper_main(job, read_fd):
    """Wait for application exit, persist the result, and reopen Exhale if possible."""
    with os.fdopen(read_fd, "rb") as parent:
        parent.read()
    result = {"log": str(job / "update.log")}
    try:
        run_update(job)
        result["success"] = True
    except Exception:
        traceback.print_exc()
        result["success"] = False
    (job / "result.json").write_text(json.dumps(result), encoding="utf-8")
    plan = json.loads((job / "plan.json").read_text(encoding="utf-8"))
    subprocess.Popen([plan["launcher"]], start_new_session=True)


if __name__ == "__main__":
    helper_main(Path(sys.argv[1]), int(sys.argv[2]))
