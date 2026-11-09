"""MONAI watershed separation, lazy imports, tiling, cancellation and model persistence."""

import json
import os
import subprocess
import sys
from fnmatch import fnmatch
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
import tomllib

from exhale.analysis.model_store import MONAI_MODEL
from exhale.analysis.segmentation_monai import instances_from_probabilities


def probabilities():
    values = np.zeros((3, 15, 23), dtype=np.float32)
    values[0] = 1
    values[:, 2:12, 2:20] = np.array([0.1, 0.1, 0.8])[:, None, None]
    for region in ((slice(4, 7), slice(4, 7)), (slice(7, 10), slice(15, 18))):
        values[(slice(None), *region)] = np.array([0.05, 0.9, 0.05])[:, None, None]
    return values


def test_boundary_and_interior_seeds_separate_touching_nuclei_without_input_changes():
    values = probabilities()
    before = values.copy()
    labels = instances_from_probabilities(values)
    assert labels.dtype == np.uint32 and labels.shape == values.shape[1:]
    assert labels[5, 5] != labels[8, 16] and labels[5, 5] > 0 and labels[8, 16] > 0
    np.testing.assert_array_equal(labels > 0, (1 - values[0]) > 0.5)
    np.testing.assert_array_equal(values, before)


def test_unseeded_components_get_fallback_markers_and_small_nuclei_are_removed():
    values = np.zeros((3, 20, 25), dtype=np.float32)
    values[0] = 1
    for region in ((slice(2, 7), slice(2, 7)), (slice(12, 17), slice(17, 22))):
        values[(slice(None), *region)] = np.array([0.1, 0.2, 0.7])[:, None, None]
    values[:, 19, 0] = [0.1, 0.8, 0.1]
    labels = instances_from_probabilities(values, min_size=20)
    assert set(np.unique(labels)) == {0, 1, 2}
    assert labels[19, 0] == 0
    assert labels[4, 4] > 0 and labels[14, 19] > 0
    assert not instances_from_probabilities(values, min_size=26).any()


def test_empty_foreground_produces_an_empty_instance_mask():
    values = np.zeros((3, 4, 5))
    values[0] = 1
    assert not instances_from_probabilities(values).any()


@pytest.mark.parametrize(
    "options",
    [
        {"seed_threshold": -1},
        {"seed_threshold": np.nan},
        {"seed_threshold": 1.1},
        {"min_size": 0},
        {"min_size": 1.5},
        {"min_size": True},
    ],
)
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValueError):
        instances_from_probabilities(probabilities(), **options)


def test_catalogue_matches_metadata_and_binary_weights_are_not_packaged():
    metadata = json.loads(
        files("exhale").joinpath("resources/models/monai_unet/metadata.json").read_text()
    )
    assert MONAI_MODEL.size == 1631368
    assert MONAI_MODEL.sha256 == metadata["sha256"]
    assert metadata["architecture"]["out_channels"] == 3
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    extras = config["project"]["optional-dependencies"]
    assert any(value.startswith("monai") for value in extras["monai"])
    assert any(value.startswith("torch") for value in extras["monai"])
    excluded = config["tool"]["setuptools"]["exclude-package-data"]["exhale"]
    assert any(fnmatch("resources/models/monai_unet/model.pt", pattern) for pattern in excluded)
    assert any(
        fnmatch("resources/models/2D_versatile_fluo_copy/weights_best.h5", pattern)
        for pattern in excluded
    )


def _run(code, *args, timeout=90):
    result = subprocess.run(
        [sys.executable, "-c", code, *map(str, args)],
        env={
            **os.environ,
            "QT_API": "pyqt6",
            "QT_QPA_PLATFORM": "offscreen",
            "CUDA_VISIBLE_DEVICES": "",
            "TF_CPP_MIN_LOG_LEVEL": "3",
        },
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_options_and_adapters_do_not_initialize_neural_runtimes():
    _run("""
import sys
from qtpy import QtWidgets
from exhale.analysis.segmentation_options_dialog import SegmentationOptionsDialog
from exhale.data.segmentation import SegmentationParameters
app=QtWidgets.QApplication([])
dialog=SegmentationOptionsDialog()
dialog.set_method('monai')
assert dialog.parameters()==SegmentationParameters(clip_percentile=99.9,
    method_options={'seed_threshold':.5,'min_size':20})
dialog.set_parameters(SegmentationParameters(clip_percentile=99,
    method_options={'seed_threshold':.7,'min_size':31}))
dialog.set_method('cellpose');dialog.set_method('monai')
assert dialog.parameters().method_options=={'seed_threshold':.7,'min_size':31}
assert not {'torch','tensorflow','monai','cellpose','dinov3'}.intersection(sys.modules)
""")


@pytest.mark.skipif(
    find_spec("torch") is None or find_spec("monai") is None,
    reason="MONAI optional backend unavailable",
)
def test_tiling_preserves_pixel_positions_and_cancellation_discards_partial_inference(tmp_path):
    _run(
        """
import sys
from pathlib import Path
import numpy as np
path=Path(sys.argv[1]);path.touch()
from exhale.analysis.segmentation_backends import prepare_segmentation_runtime
prepare_segmentation_runtime()
import torch
torch.set_num_threads(2)
from exhale.analysis import segmentation_monai as adapter

def predictor(x):
    return torch.cat([x,1-x,torch.zeros_like(x)],dim=1)
adapter._model=lambda *_: predictor
captured=[]
def postprocess(values,**kwargs):
    captured.append(values.copy())
    return np.zeros(values.shape[1:],np.uint32)
adapter.instances_from_probabilities=postprocess
for shape in ((300,349),(31,45)):
    image=np.arange(np.prod(shape),dtype=np.float32).reshape(shape)
    original=image.copy()
    result=adapter.segment_monai(image,model_path=str(path))
    x=torch.from_numpy((image-image.min())/(image.max()-image.min()))[None,None]
    expected=predictor(x).softmax(dim=1)[0].numpy()
    np.testing.assert_allclose(captured[-1],expected,atol=2e-6)
    np.testing.assert_array_equal(image,original)
    assert result.shape==shape
captured.clear()
count=0
def cancelled(message):
    global count
    if '(tile' in message:
        count+=1
        if count==2:raise InterruptedError('cancelled')
try:
    adapter.segment_monai(np.ones((300,349),np.float32),model_path=str(path),callback=cancelled)
except InterruptedError:pass
else:raise AssertionError('Cancellation did not escape inference')
assert count==2 and not captured
""",
        tmp_path / "weights.pt",
    )


@pytest.mark.skipif(
    find_spec("torch") is None or find_spec("monai") is None,
    reason="MONAI optional backend unavailable",
)
def test_model_batch_reuses_weights_and_roundtrips_candidates_and_options(tmp_path):
    _run(
        """
import sys
from pathlib import Path
import numpy as np,h5py,hashlib
from dataclasses import replace
from exhale.analysis.segmentation_backends import prepare_segmentation_runtime
prepare_segmentation_runtime()
import torch
torch.set_num_threads(2)
from exhale.analysis import segmentation_monai as adapter
from exhale.analysis.segmentationbatch import BatchSegmentationWorker
from exhale.data.projectdata import ProjectData,SegmentationResult
from exhale.data.segmentation import SegmentationParameters
from exhale.data.segmentationbatch import SegmentationBatchJob
from exhale.data.source_refs import open_source
from exhale.project.projectio import save_project,load_project
root=Path(sys.argv[1]);project=ProjectData()
from monai.networks.nets import UNet
from exhale.analysis import model_store
checkpoint=root/'test-model.pt'
network=UNet(spatial_dims=2,in_channels=1,out_channels=3,channels=(16,32,64,128),strides=(2,2,2),num_res_units=2)
torch.save(network.state_dict(),checkpoint)
model_store.MONAI_MODEL=replace(model_store.MONAI_MODEL,url=checkpoint.as_uri(),
    size=checkpoint.stat().st_size,sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
y,x=np.mgrid[:41,:47]
image=np.exp(-((y-20)**2+(x-23)**2)/40).astype(np.float32)
jobs=[]
for i in range(2):
    path=root/f'source{i}.h5'
    with h5py.File(path,'w') as handle:
        handle.attrs['default']='entry';handle.create_dataset('entry/plotselect/P',data=image)
    project.register_source(open_source(str(path)))
    sample=next(reversed(project.samples.values()))
    jobs.append(SegmentationBatchJob(sample.sample_id,sample.name,sample.channels['P'].ref))
params=SegmentationParameters(clip_percentile=99.9,method_options={'seed_threshold':.6,'min_size':8})
worker=BatchSegmentationWorker(jobs,project.sources,method_id='monai',parameters=params,model_directory=root/'model-store')
outputs=[];failures=[]
worker.sample_finished.connect(lambda job,output:outputs.append((job,output)))
worker.sample_failed.connect(lambda *args:failures.append(args))
completed=worker.execute()
assert not failures and len(completed)==2 and len(outputs)==2
assert adapter._model.cache_info().misses==1 and adapter._model.cache_info().hits==1
for job,output in outputs:
    assert output.labels.shape==image.shape and output.model_id=='monai-unet-xrf'
    assert output.model_version.startswith('sha256:')
    candidate=project.add_segmentation_candidate(SegmentationResult(job.sample_id,'monai',job.input_ref,params,output))
save_project(project,root/'project.xhp')
restored=ProjectData();assert not load_project(restored,root/'project.xhp')
for job,output in outputs:
    candidate=restored.segmentation_histories[job.sample_id].active
    assert candidate.result.method_id=='monai' and candidate.result.parameters==params
    np.testing.assert_array_equal(candidate.result.output.labels,output.labels)
    np.testing.assert_array_equal(project.assets[job.input_ref.source_id].source.load_array(job.input_ref),image)
for model in (project,restored):
    for source in model.sources.values():source.close()
""",
        tmp_path,
    )
