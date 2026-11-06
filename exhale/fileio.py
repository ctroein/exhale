"""Staging paths for atomic output with ordinary filesystem permissions."""

from contextlib import contextmanager
from pathlib import Path
from secrets import token_hex
from shutil import rmtree


def create_staging_file(parent: Path, *, prefix: str, suffix: str = ".tmp") -> Path:
    """Reserve a sibling file exclusively, inheriting default ACLs and the umask."""
    while True:
        path = Path(parent) / f"{prefix}{token_hex(16)}{suffix}"
        try:
            with path.open("xb"):
                pass
        except FileExistsError:
            continue
        return path


@contextmanager
def staging_directory(parent: Path, *, prefix: str):
    """Stage output with normal directory permissions and remove unpublished data."""
    while True:
        path = Path(parent) / f"{prefix}{token_hex(16)}"
        try:
            path.mkdir()
        except FileExistsError:
            continue
        break
    try:
        yield path
    finally:
        if path.exists():
            rmtree(path)
