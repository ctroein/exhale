"""Transfer integrity, cancellation and reuse of downloaded trained models."""

import hashlib
import stat
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from exhale.analysis import model_store
from exhale.analysis.analysisworker import AnalysisWorker
from exhale.analysis.model_store import ModelDownloadError, TrainedModel, ensure_model


@pytest.fixture
def server():
    state = {"payload": bytes(range(256)) * 8192, "requests": 0, "mode": "ok"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            state["requests"] += 1
            if state["mode"] == "missing":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(state["payload"])))
            self.end_headers()
            body = state["payload"]
            if state["mode"] == "truncated":
                body = body[: len(body) // 2]
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    model = TrainedModel(
        "test",
        "1",
        "weights.pt",
        f"http://127.0.0.1:{http.server_port}/model",
        len(state["payload"]),
        hashlib.sha256(state["payload"]).hexdigest(),
    )
    try:
        yield model, state
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def test_download_is_verified_then_reused_offline(server, tmp_path):
    model, state = server
    messages = []
    path = ensure_model(model, tmp_path, progress=lambda *args: messages.append(args))
    assert path.read_bytes() == state["payload"]
    ordinary = path.parent / "ordinary-file"
    ordinary.touch()
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(ordinary.stat().st_mode)
    assert state["requests"] == 1
    assert messages[0] == ("Downloading", 0, model.size)
    assert messages[-1] == ("Downloading", model.size, model.size)
    timestamp = path.stat().st_mtime_ns
    state["mode"] = "missing"
    assert ensure_model(model, tmp_path) == path
    assert path.stat().st_mtime_ns == timestamp
    assert state["requests"] == 1
    assert not list(tmp_path.rglob("*.part"))


def test_existing_model_is_checked_before_reuse(server, tmp_path):
    model, state = server
    path = model.local_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(state["payload"])
    state["mode"] = "missing"
    progress = []
    assert ensure_model(model, tmp_path, progress=lambda *args: progress.append(args)) == path
    assert progress[0] == ("Verifying", 0, model.size)
    assert progress[-1] == ("Verifying", model.size, model.size)
    assert not state["requests"]


def test_corrupt_cached_model_is_replaced_only_after_successful_verification(server, tmp_path):
    model, state = server
    path = model.local_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"X" * model.size)
    ensure_model(model, tmp_path)
    assert path.read_bytes() == state["payload"]
    path.write_bytes(b"Y" * model.size)
    state["mode"] = "missing"
    with pytest.raises(ModelDownloadError, match="HTTP 404"):
        ensure_model(model, tmp_path)
    assert path.read_bytes() == b"Y" * model.size
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("failure", ["checksum", "truncated", "size", "missing"])
def test_failed_transfer_never_installs_partial_or_wrong_weights(server, tmp_path, failure):
    model, state = server
    if failure == "checksum":
        model = replace(model, sha256="0" * 64)
    elif failure == "size":
        model = replace(model, size=model.size + 1)
    else:
        state["mode"] = failure
    with pytest.raises(ModelDownloadError):
        ensure_model(model, tmp_path)
    assert not model.local_path(tmp_path).exists()
    assert not list(tmp_path.rglob("*.part"))


def test_cancellation_during_transfer_preserves_existing_file(server, tmp_path, monkeypatch):
    model, state = server
    path = model.local_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = b"old incomplete file"
    path.write_bytes(original)
    ticks = iter(range(100000))
    monkeypatch.setattr(model_store, "monotonic", lambda: next(ticks))
    cancelled = False

    def progress(phase, done, total):
        nonlocal cancelled
        if phase == "Downloading" and done > 0:
            cancelled = True

    with pytest.raises(InterruptedError):
        ensure_model(model, tmp_path, progress=progress, cancelled=lambda: cancelled)
    assert path.read_bytes() == original
    assert not list(tmp_path.rglob("*.part"))


def test_cancellation_during_checksum_never_starts_a_download(server, tmp_path):
    model, state = server
    path = model.local_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(state["payload"])
    cancelled = False

    def progress(phase, done, total):
        nonlocal cancelled
        cancelled = True

    with pytest.raises(InterruptedError):
        ensure_model(model, tmp_path, progress=progress, cancelled=lambda: cancelled)
    assert not state["requests"]
    assert path.read_bytes() == state["payload"]


def test_model_directory_failure_is_a_user_facing_error(server, tmp_path):
    model, _ = server
    root = tmp_path / "not-a-directory"
    root.write_text("file")
    with pytest.raises(ModelDownloadError, match="Could not obtain"):
        ensure_model(model, root)


def test_transfer_progress_is_throttled(server, tmp_path, monkeypatch):
    model, _ = server
    monkeypatch.setattr(model_store, "monotonic", lambda: 100.0)
    messages = []
    ensure_model(model, tmp_path, progress=lambda *args: messages.append(args))
    assert messages == [("Downloading", 0, model.size), ("Downloading", model.size, model.size)]


@pytest.mark.parametrize("method_id", ("cellpose", "smp", "stardist", "monai"))
def test_worker_acquires_the_model_before_calling_inference(
    server, tmp_path, monkeypatch, method_id
):
    model, _ = server
    monkeypatch.setattr(model_store, "model_for_method", lambda _method: model)
    from exhale.analysis import segmentation_backends
    from exhale.data.segmentation import SegmentationOutput

    seen = []

    def infer(method, image, parameters, *, model_path, callback):
        seen.append(model_path)
        assert model.local_path(tmp_path).read_bytes() == server[1]["payload"]
        return SegmentationOutput(np.ones_like(image, dtype=np.uint32), "test", "1")

    monkeypatch.setattr(segmentation_backends, "run_segmentation", infer)
    worker = AnalysisWorker(np.ones((2, 3)), method_id=method_id, model_directory=tmp_path)
    worker.execute()
    assert seen == [str(model.local_path(tmp_path))]


def test_download_failure_never_reaches_inference(server, tmp_path, monkeypatch):
    model, state = server
    state["mode"] = "missing"
    monkeypatch.setattr(model_store, "model_for_method", lambda _method: model)
    worker = AnalysisWorker(np.ones((2, 3)), method_id="cellpose", model_directory=tmp_path)
    success, failure = [], []
    worker.finished.connect(success.append)
    worker.failed.connect(failure.append)
    worker.run()
    assert not success
    assert len(failure) == 1
    assert "HTTP 404" in worker.model_error


def test_cancel_during_a_network_failure_remains_a_cancellation(server, tmp_path, monkeypatch):
    import urllib.error

    model, _ = server
    cancelled = False

    def connection_failed(*_args, **_kwargs):
        nonlocal cancelled
        cancelled = True
        raise urllib.error.URLError("connection interrupted")

    monkeypatch.setattr(model_store.urllib.request, "urlopen", connection_failed)
    with pytest.raises(InterruptedError):
        ensure_model(model, tmp_path, cancelled=lambda: cancelled)
    assert not model.local_path(tmp_path).exists()
    assert not list(tmp_path.rglob("*.part"))
