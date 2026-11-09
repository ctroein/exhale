"""Clustering registry with method-owned execution and options adapters."""

from collections.abc import Callable
from dataclasses import dataclass

from ..data.clustering import DEFAULT_CLUSTERING_METHOD
from ..data.projectdata import ClusteringParameters


def _intensity_partition(arrays, job, parameters, callback, *, progress=None):
    """Partition raw intensities and extract connected element regions."""
    from ..xrf_refcopy.xrf_element_channel import ElementChannel
    from ..xrf_refcopy.xrf_sample_class import XRFSample

    sample = XRFSample(job.sample_name)
    for index, (key, name, array) in enumerate(zip(job.keys, job.names, arrays, strict=True)):
        if progress is not None:
            progress(index, len(arrays), name)
        channel = ElementChannel(name, array)
        try:
            channel.process(min_k=parameters.min_k, max_k=parameters.max_k, callback=callback)
        except ValueError as error:
            raise ValueError(f"{name} ({key}): {error}") from error
        if progress is not None:
            progress(index + 1, len(arrays), name)
        sample.elements[key] = channel
    return sample


def _options(parent):
    from ..tooltips import ANALYSIS_SETTINGS_DIALOG, apply_tooltips
    from .analysis_settings_dialog import AnalysisSettingsDialog

    dialog = AnalysisSettingsDialog(parent)
    apply_tooltips(dialog, ANALYSIS_SETTINGS_DIALOG)
    dialog.adjustSize()
    return dialog


def _parameters(dialog):
    minimum, maximum = dialog.clusterMinK.value(), dialog.clusterMaxK.value()
    if minimum > maximum:
        raise ValueError("Minimum class count exceeds the maximum.")
    return ClusteringParameters(minimum, maximum)


def _restore(dialog, parameters):
    dialog.clusterMinK.setValue(parameters.min_k)
    dialog.clusterMaxK.setValue(parameters.max_k)


@dataclass(frozen=True)
class ClusteringMethod:
    """Supply execution and options without coupling the queue or viewer to an algorithm.

    Compute accepts an optional progress(completed, total, element_name) callback.
    """

    method_id: str
    name: str
    compute: Callable
    create_options: Callable
    parameters: Callable
    restore_options: Callable


CLUSTERING_METHODS = (
    ClusteringMethod(
        DEFAULT_CLUSTERING_METHOD,
        "Intensity partition",
        _intensity_partition,
        _options,
        _parameters,
        _restore,
    ),
)


def clustering_method(method_id):
    """Resolve a stable identifier without importing segmentation runtimes."""
    for method in CLUSTERING_METHODS:
        if method.method_id == method_id:
            return method
    raise ValueError(f"Unknown clustering method: {method_id!r}")
