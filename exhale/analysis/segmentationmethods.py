"""Lightweight metadata and factories for available segmentation methods."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec


@dataclass(frozen=True)
class SegmentationMethod:
    """Describe one segmentation implementation without importing its backend."""

    method_id: str
    name: str
    required_modules: tuple[str, ...]
    has_options: bool = False

    def unavailable_reason(self) -> str | None:
        missing = [module for module in self.required_modules if find_spec(module) is None]
        if not missing:
            return None
        return "Missing dependency: " + ", ".join(missing)

    def create_worker(self, *args, **kwargs):
        from .analysisworker import AnalysisWorker

        return AnalysisWorker(*args, method_id=self.method_id, **kwargs)


SEGMENTATION_METHODS = (
    SegmentationMethod(
        method_id="stardist",
        name="StarDist",
        required_modules=("stardist", "tensorflow", "csbdeep"),
    ),
)
SEGMENTATION_METHODS += (
    SegmentationMethod(
        method_id="cellpose",
        name="Cellpose",
        required_modules=("torch", "torchvision", "cellpose", "dinov3"),
        has_options=True,
    ),
)
SEGMENTATION_METHODS_BY_ID = {method.method_id: method for method in SEGMENTATION_METHODS}


def segmentation_method(method_id: str) -> SegmentationMethod:
    """Return registered metadata for a stable method identifier."""
    try:
        return SEGMENTATION_METHODS_BY_ID[method_id]
    except KeyError as exc:
        raise ValueError(f"Unknown segmentation method {method_id!r}") from exc


def check_installed_backends() -> None:
    """Exercise installed backends; reject partial installations instead of skipping them."""
    for method in SEGMENTATION_METHODS:
        # A framework alone may belong to an unrelated application.
        if find_spec(method.method_id) is None:
            print(f"{method.name}: not installed")
            continue
        reason = method.unavailable_reason()
        if reason is not None:
            raise RuntimeError(f"{method.name}: {reason}")
        if method.method_id == "stardist":
            import_module("tensorflow")
            import_module("stardist.models")
        else:
            module = import_module("cellpose.vit")
            if not callable(getattr(module, "dinov3_vitl16", None)):
                raise RuntimeError("CellposeDINO is unavailable: DINOv3 failed to import")
        print(f"{method.name}: import check passed")
