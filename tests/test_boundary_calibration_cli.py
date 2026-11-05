"""Saved-project experiments are non-destructive and produce inspectable diagnostics."""

import json
import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np

from exhale.data.projectdata import ProjectData, SegmentationResult
from exhale.data.segmentation import SegmentationOutput, SegmentationParameters
from exhale.data.source_refs import open_source
from exhale.project.projectio import save_project

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "fit_boundary_parameters.py"


def test_saved_project_calibration_and_listing_do_not_change_sources_or_initialize_models(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    y, x = np.mgrid[:70, :70]
    labels = np.zeros(y.shape, np.uint32)
    for identity, (cy, cx) in enumerate(((15, 15), (15, 48), (48, 15), (48, 48)), start=1):
        labels[(y - cy) ** 2 + (x - cx) ** 2 <= 36] = identity
    data = (labels > 0).astype(float) * 12 + 0.1
    source = project_dir / "maps.h5"
    with h5py.File(source, "w") as handle:
        handle.attrs["default"] = "entry"
        handle.create_dataset("entry/plotselect/P", data=data)
    model = ProjectData()
    model.register_source(open_source(str(source)))
    sample = next(iter(model.samples.values()))
    sample.name = "Synthetic sample"
    candidate = model.add_segmentation_candidate(
        SegmentationResult(
            sample.sample_id,
            "stardist",
            sample.channels["P"].ref,
            SegmentationParameters(),
            SegmentationOutput(labels, "test-model", "1"),
        )
    )
    candidate.name = "Test mask"
    save_project(model, project_dir / "project.xhp")
    for opened in model.sources.values():
        opened.close()
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in project_dir.rglob("*") if p.is_file()
    }
    env = {**os.environ, "QT_API": "pyqt6", "QT_QPA_PLATFORM": "offscreen"}
    listing_code = """
import runpy, sys
sys.argv = [sys.argv[1], sys.argv[2], '--list']
runpy.run_path(sys.argv[0], run_name='__main__')
assert not {'torch', 'tensorflow', 'stardist'}.intersection(sys.modules)
"""
    listing = subprocess.run(
        [sys.executable, "-c", listing_code, str(TOOL), str(project_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listing.returncode == 0, listing.stderr
    assert "Synthetic sample" in listing.stdout and "Test mask" in listing.stdout
    output = tmp_path / "results"
    command = [
        sys.executable,
        str(TOOL),
        str(project_dir),
        "--sample",
        "Synthetic sample",
        "--mask",
        "Test mask",
        "--output",
        str(output),
        "--max-segments",
        "3",
        "--iterations",
        "2",
        "--previews",
        "1",
    ]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / "report.json").read_text())
    assert set(report["best"]) == {"edges", "region"}
    assert report["sources"][0]["reference"]["candidate_id"] == candidate.candidate_id
    assert set(report["summaries"]["validation"]) == {"initial", "edges", "region"}
    assert (output / "scores.csv").is_file() and (output / "example_001.png").is_file()
    with np.load(output / "example_001.npz") as preview:
        assert set(preview.files) == {"image", "initial", "target", "edges", "region"}
        assert np.isin(preview["image"], (0.1, 12.1)).all()
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
    refused = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert refused.returncode != 0 and "already exists" in refused.stderr
    assert "Traceback" not in refused.stderr
