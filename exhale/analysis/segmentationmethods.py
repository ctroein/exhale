"""Lightweight metadata and factories for available segmentation methods."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec


@dataclass(frozen=True)
class SegmentationMethod:
    """Describe one segmentation implementation without importing its backend."""

    method_id: str
    name: str
    required_modules: tuple[str, ...]
    supports_cluster_distances: bool = False

    def unavailable_reason(self) -> str | None:
        missing = [module for module in self.required_modules if find_spec(module) is None]
        if not missing:
            return None
        return "Missing dependency: " + ", ".join(missing)

    def create_worker(self, *args, **kwargs):
        if self.method_id != "stardist":
            raise ValueError(f"Unknown segmentation method {self.method_id!r}")
        from .analysisworker import AnalysisWorker

        return AnalysisWorker(*args, **kwargs)


SEGMENTATION_METHODS = (
    SegmentationMethod(
        method_id="stardist",
        name="StarDist",
        required_modules=("stardist", "tensorflow"),
        supports_cluster_distances=True,
    ),
)
SEGMENTATION_METHODS_BY_ID = {method.method_id: method for method in SEGMENTATION_METHODS}


def segmentation_method(method_id: str) -> SegmentationMethod:
    """Return registered metadata for a stable method identifier."""
    try:
        return SEGMENTATION_METHODS_BY_ID[method_id]
    except KeyError as exc:
        raise ValueError(f"Unknown segmentation method {method_id!r}") from exc
