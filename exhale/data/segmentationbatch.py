"""Stable per-sample inputs and channel suggestions for a segmentation queue."""

from dataclasses import dataclass

from .source_refs import ElementRef


@dataclass(frozen=True)
class SegmentationBatchJob:
    """One queued sample/channel; method and parameter snapshots belong to the batch."""

    sample_id: str
    sample_name: str
    input_ref: ElementRef


def batch_channels(project, sample):
    """Offer effective, available maps without materializing their intensities."""
    return sorted(
        (
            channel
            for channel in sample.effective_channels(project.project_channels).values()
            if channel.ref is not None
            and channel.ref.source_id in project.assets
            and project.assets[channel.ref.source_id].is_available
            and channel.available
        ),
        key=lambda channel: (channel.name.casefold(), channel.key.casefold()),
    )


def suggested_batch_channel(project, sample, method_id, *, current_ref=None):
    """Prefer existing assignments, then a P or P_* channel, otherwise require a choice."""
    channels = batch_channels(project, sample)
    available = {channel.ref for channel in channels}
    preview = project.segmentation_previews.get(sample.sample_id, {}).get(method_id)
    history = project.segmentation_histories.get(sample.sample_id)
    previous = None if history is None else history.latest_for_method(method_id)
    for ref in (
        current_ref,
        None if preview is None else preview.input_ref,
        None if previous is None else previous.result.input_ref,
        None if history is None or history.active is None else history.active.result.input_ref,
    ):
        if ref in available:
            return ref
    return next((c.ref for c in channels if c.key == "P" or c.key.startswith("P_")), None)
