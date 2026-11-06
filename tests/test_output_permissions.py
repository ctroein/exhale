"""Published output inherits creation permissions rather than tempfile restrictions."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from exhale.fileio import create_staging_file, staging_directory


@pytest.mark.skipif(os.name != "posix", reason="POSIX creation permissions")
@pytest.mark.parametrize("mask", [0o002, 0o027])
def test_staging_and_atomic_writers_obey_umask(tmp_path, mask):
    # Isolate the process-wide umask from the test runner and its worker threads.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sys
from pathlib import Path
import numpy as np
from exhale.fileio import create_staging_file, staging_directory
from exhale.project.projectio import save_project_state
from exhale.analysis.segmentationio import save_segmentation, save_xrf_sample
from exhale.data.segmentation import SegmentationOutput
from exhale.xrf_refcopy.xrf_sample_class import XRFSample
root = Path(sys.argv[1])
os.umask(int(sys.argv[2]))
create_staging_file(root, prefix="file-").rename(root / "file")
with staging_directory(root, prefix="dir-") as stage:
    (stage / "child").write_text("data")
    stage.rename(root / "published")
for _ in range(2):
    save_project_state({"test": True}, root / "project.xhp")
save_segmentation(SegmentationOutput(np.ones((2, 2), dtype=np.uint32), "model", "1"),
                  root / "segmentation.h5", method_id="test")
save_xrf_sample(XRFSample("sample"), root / "clusters.h5")
""",
            str(tmp_path),
            str(mask),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    for path in tmp_path.rglob("*"):
        expected = (0o777 if path.is_dir() else 0o666) & ~mask
        assert stat.S_IMODE(path.stat().st_mode) == expected, path


def test_unpublished_directory_is_removed_on_failure(tmp_path):
    with pytest.raises(ValueError, match="failed"):
        with staging_directory(tmp_path, prefix="stage-") as stage:
            (stage / "partial").write_text("data")
            raise ValueError("failed")
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(not shutil.which("setfacl"), reason="setfacl unavailable")
def test_staging_inherits_parent_default_acl(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir()
    subprocess.run(
        ["setfacl", "-m", "d:u::rwx,d:g::rwx,d:m::rwx,d:o::---", str(parent)], check=True
    )
    ordinary_file = parent / "ordinary"
    ordinary_file.touch()
    ordinary_dir = parent / "directory"
    ordinary_dir.mkdir()
    staged_file = create_staging_file(parent, prefix="file-")
    with staging_directory(parent, prefix="stage-") as stage:
        assert stat.S_IMODE(stage.stat().st_mode) == stat.S_IMODE(ordinary_dir.stat().st_mode)
        assert stat.S_IMODE(staged_file.stat().st_mode) == stat.S_IMODE(
            ordinary_file.stat().st_mode
        )
        assert stage.stat().st_mode & stat.S_IWGRP
        assert staged_file.stat().st_mode & stat.S_IWGRP
