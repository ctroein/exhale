"""Versioned trained-model metadata and cancellable, verified local downloads."""

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


@dataclass(frozen=True)
class TrainedModel:
    """One independently versioned release asset with its expected contents."""

    model_id: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str

    def local_path(self, directory: str | Path) -> Path:
        return Path(directory).expanduser() / self.model_id / self.version / self.filename


CELLPOSE_MODEL = TrainedModel(
    model_id="cellpose-dino-xrf",
    version="1",
    filename="cellpose-dino-xrf-v1.pt",
    url="https://github.com/ctroein/exhale/releases/download/models-v1/cellpose-dino-xrf-v1.pt",
    size=1213986797,
    sha256="74e3cf36841e4fbbea45ec56ef11ecb81574e52cfb2c1919a8d588f72f15c71b",
)

MODEL_DIRECTORY_SETTING = "segmentation/model_directory"
_CHUNK_SIZE = 256 * 1024
# Trust verification only while the file's identity, size and modification time match.
_verified_files = {}


class ModelDownloadError(RuntimeError):
    """An expected model transfer, integrity or local-storage failure."""


def model_for_method(method_id: str) -> TrainedModel | None:
    """Return downloadable weights; StarDist continues using its bundled model."""
    return CELLPOSE_MODEL if method_id == "cellpose" else None


def _file_identity(path):
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


def ensure_model(
    model: TrainedModel,
    directory: str | Path,
    *,
    progress=lambda _phase, _done, _total: None,
    cancelled=lambda: False,
) -> Path:
    """Reuse verified weights or download atomically, leaving no usable partial file.

    Cancellation is checked between network reads and checksum chunks. Progress is
    throttled to four updates per second, plus phase boundaries. Failed replacement
    never alters an existing file. Verification is cached for an unchanged file.
    """
    temporary = None
    last_update = 0.0

    def check_cancelled():
        if cancelled():
            raise InterruptedError("Model acquisition cancelled")

    def notify(phase, done):
        nonlocal last_update
        check_cancelled()
        now = monotonic()
        if done in (0, model.size) or now - last_update >= 0.25:
            progress(phase, done, model.size)
            last_update = now

    try:
        destination = model.local_path(directory).resolve()
        check_cancelled()
        if destination.is_file() and destination.stat().st_size == model.size:
            identity = _file_identity(destination)
            if _verified_files.get(destination) == (identity, model.sha256):
                return destination
            digest = hashlib.sha256()
            completed = 0
            notify("Verifying", 0)
            with destination.open("rb") as stream:
                while chunk := stream.read(_CHUNK_SIZE):
                    digest.update(chunk)
                    completed += len(chunk)
                    notify("Verifying", completed)
            if digest.hexdigest() == model.sha256:
                check_cancelled()
                _verified_files[destination] = (identity, model.sha256)
                return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        notify("Downloading", 0)
        request = urllib.request.Request(model.url, headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != model.size:
                raise ModelDownloadError("The model download has an unexpected file size.")
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
            ) as stream:
                temporary = Path(stream.name)
                digest = hashlib.sha256()
                completed = 0
                read = getattr(response, "read1", response.read)
                while chunk := read(_CHUNK_SIZE):
                    check_cancelled()
                    completed += len(chunk)
                    if completed > model.size:
                        raise ModelDownloadError("The model download is larger than expected.")
                    stream.write(chunk)
                    digest.update(chunk)
                    notify("Downloading", completed)
                stream.flush()
                os.fsync(stream.fileno())
        check_cancelled()
        if completed != model.size:
            raise ModelDownloadError("The model download ended before the whole file arrived.")
        if digest.hexdigest() != model.sha256:
            raise ModelDownloadError("The downloaded model failed its checksum verification.")
        os.replace(temporary, destination)
        temporary = None
        _verified_files[destination] = (_file_identity(destination), model.sha256)
        return destination
    except InterruptedError:
        raise
    except ModelDownloadError:
        check_cancelled()
        raise
    except urllib.error.HTTPError as exc:
        exc.close()
        check_cancelled()
        if exc.code == 404:
            raise ModelDownloadError(
                "The trained model is not available at its download URL yet (HTTP 404)."
            ) from exc
        raise ModelDownloadError(
            f"The model download failed: HTTP {exc.code} {exc.reason}."
        ) from exc
    except urllib.error.URLError as exc:
        check_cancelled()
        raise ModelDownloadError(f"Could not download the trained model: {exc.reason}.") from exc
    except (OSError, ValueError) as exc:
        check_cancelled()
        raise ModelDownloadError(f"Could not obtain the trained model: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
