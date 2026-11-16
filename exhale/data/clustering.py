"""Clustering method identity, shared abundance defaults and immutable batch inputs."""

from dataclasses import dataclass

from .source_refs import ElementRef

DEFAULT_CLUSTERING_METHOD = "intensity-partition"
ABUNDANCE_DEFAULTS = {
    "min_cluster_size": 10,
    "radius": 2.0,
    "cutoff_scale": 3.0,
    "auto_cutoff": True,
    "prominence": 16.0,
}


@dataclass(frozen=True)
class ClusteringJob:
    """One sample's enabled maps, captured before execution starts."""

    sample_id: str
    sample_name: str
    refs: tuple[ElementRef, ...]
    names: tuple[str, ...]
    keys: tuple[str, ...]


def clustering_job(project, sample):
    """Use every enabled sample element, in stable name order."""
    channels = sorted(
        sample.effective_channels(project.project_channels).values(),
        key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
    )
    return ClusteringJob(
        sample.sample_id,
        sample.name,
        tuple(channel.ref for channel in channels),
        tuple(channel.name for channel in channels),
        tuple(channel.key for channel in channels),
    )
