#!/usr/bin/env python3
"""JSON persistence and path relocation for complete Exhale projects."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..analysis.segmentationio import (
    candidate_relative_path,
    clustering_relative_path,
    load_segmentation,
    load_xrf_sample,
    save_candidate,
)
from ..data.elementsettings import ElementSettings, ElementSettingsDefaults, Normalizers
from ..data.imagesettings import Colorschemes, ImageSettings, Layouts, Scalebars
from ..data.projectdata import (
    ChannelOverride,
    ClusteringParameters,
    ClusteringResult,
    LayerPresentation,
    ProjectData,
    SegmentationLayerSettings,
    SegmentationParameters,
    SegmentationPreview,
    SegmentationResult,
)
from ..data.segmentation import SegmentationPostprocessing
from ..data.segmentationediting import SegmentationEditSession
from ..data.segmentationhistory import SegmentationCandidate, SegmentationHistory, SegmentationRun
from ..data.source_refs import ElementRef, LoadedSource, open_source
from ..fileio import create_staging_file

PROJECT_FORMAT = "exhale-project"
PROJECT_VERSION = 6


def _layer_settings_to_json(settings: SegmentationLayerSettings) -> dict:
    return {
        "order": list(settings.order),
        "layers": {
            key: {
                "visible": layer.visible,
                "opacity": layer.opacity,
                "blending": layer.blending,
                "color": None if layer.color is None else list(layer.color),
                "label_mode": layer.label_mode,
                "palette_index": layer.palette_index,
                "gain": layer.gain,
            }
            for key, layer in sorted(settings.layers.items())
        },
    }


def _layer_settings_from_json(obj) -> SegmentationLayerSettings:
    if not isinstance(obj, dict):
        return SegmentationLayerSettings()
    layers = {}
    for key, layer in obj.get("layers", {}).items():
        color = layer.get("color")
        layers[key] = LayerPresentation(
            visible=bool(layer["visible"]),
            opacity=float(layer["opacity"]),
            blending=str(layer["blending"]),
            color=None if color is None else tuple(map(float, color)),
            label_mode=layer.get("label_mode"),
            palette_index=(
                None if layer.get("palette_index") is None else int(layer["palette_index"])
            ),
            gain=None if layer.get("gain") is None else float(layer["gain"]),
        )
    return SegmentationLayerSettings(tuple(map(str, obj.get("order", ()))), layers)


def asset_path_to_json(asset, project_dir, external_data_root):
    """Serialize an asset path with the most useful relocation information."""
    path = Path(asset.path).resolve()
    obj = {"absolute": str(Path(asset.original_path or asset.path).resolve())}
    if project_dir is not None:
        try:
            obj["project_relative"] = str(path.relative_to(Path(project_dir).resolve()))
            return obj
        except ValueError:
            pass
    if external_data_root is not None:
        try:
            obj["external_relative"] = str(path.relative_to(Path(external_data_root).resolve()))
        except ValueError:
            pass
    obj["current_absolute"] = str(path)
    return obj


def asset_path_from_json(obj, project_dir, external_data_root):
    """Resolve a saved asset path, preferring relocatable forms that exist.

    If none exist, return the first candidate so the asset can remain in the
    project as an unavailable source and be relocated later.
    """
    candidates = []
    if project_dir is not None and "project_relative" in obj:
        candidates.append(Path(project_dir) / obj["project_relative"])
    if external_data_root is not None and "external_relative" in obj:
        candidates.append(Path(external_data_root) / obj["external_relative"])
    for key in ("current_absolute", "absolute"):
        if key in obj:
            candidates.append(Path(obj[key]))
    return str(next((path for path in candidates if path.exists()), candidates[0]).resolve())


def _ref_to_json(ref: ElementRef) -> dict[str, str]:
    return ref.to_json()


def _elementsettings_to_json(es) -> dict[str, Any]:
    return {
        "ref": _ref_to_json(es.ref),
        "name": es.name,
        "normalizer": es.normalizer.name,
        "gamma": es.gamma,
        "trf_range": [float(value) for value in es.trfRange],
        "data_range": [float(value) for value in es.dataRange],
        "min_positive": float(es.minPositive),
    }


def _apply_elementsettings_json(es, obj: dict[str, Any]) -> None:
    es.name = obj["name"]
    es.normalizer = Normalizers[obj["normalizer"]]
    es.gamma = obj["gamma"]
    es.trfRange = list(obj["trf_range"])


def _elementsettings_from_json(ref, source, defaults, obj):
    if source.is_open:
        settings = ElementSettings(ref=ref, data=source.channel_data(ref), defaults=defaults)
    else:
        settings = ElementSettings.__new__(ElementSettings)
        settings.ref = ref
        settings.data_source = source.channel_data(ref)
        settings.dataRange = tuple(obj["data_range"])
        settings.minPositive = obj["min_positive"]
        settings.color = None
    _apply_elementsettings_json(settings, obj)
    return settings


def _settings_ref_to_json(settings):
    return None if settings is None else _ref_to_json(settings.ref)


def _settings_from_ref(obj, settings_by_ref):
    return None if obj is None else settings_by_ref[ElementRef.from_json(obj)]


def _image_options_to_json(image, *, include_resolution=False):
    """Serialize image presentation, including resolution only for defaults."""
    obj = {
        "layout": image.layout.name,
        "scalebar": image.scalebar.name,
        "scalebar_color": list(image.scalebarColor),
        "scalebar_bg_color": list(image.scalebarBgColor),
        "scalebar_bg_alpha": image.scalebarBgAlpha,
        "fontsize": image.fontsize,
        "border_color": list(image.borderColor),
        "border_width": image.borderWidth,
        "panel_labels": image.panelLabels,
        "panel_label_color": list(image.panelLabelColor),
        "element_labels": image.elementLabels,
        "element_labels_colored": image.elementLabelsColored,
        "element_borders": image.elementBorders,
        "colorscheme": image.colorscheme.name,
        "custom_colors": (None if image.customColors is None else image.customColors.tolist()),
        "dpi": image.dpi,
        "clip_colors": image.clipColors,
    }
    if include_resolution:
        obj["resolution"] = list(image.resolution)
    return obj


def _apply_image_options(image, obj):
    """Apply saved presentation fields, retaining defaults for absent fields."""
    import numpy as np

    image.layout = Layouts[obj.get("layout", image.layout.name)]
    image.scalebar = Scalebars[obj.get("scalebar", image.scalebar.name)]
    image.scalebarColor = list(obj.get("scalebar_color", image.scalebarColor))
    image.scalebarBgColor = list(obj.get("scalebar_bg_color", image.scalebarBgColor))
    image.scalebarBgAlpha = obj.get("scalebar_bg_alpha", image.scalebarBgAlpha)
    image.fontsize = obj.get("fontsize", image.fontsize)
    image.borderColor = obj.get("border_color", image.borderColor)
    image.borderWidth = obj.get("border_width", image.borderWidth)
    image.panelLabels = obj.get("panel_labels", image.panelLabels)
    image.panelLabelColor = obj.get("panel_label_color", image.panelLabelColor)
    image.elementLabels = obj.get("element_labels", image.elementLabels)
    image.elementLabelsColored = obj.get("element_labels_colored", image.elementLabelsColored)
    image.elementBorders = obj.get("element_borders", image.elementBorders)
    image.colorscheme = Colorschemes[obj.get("colorscheme", image.colorscheme.name)]
    image.customColors = obj.get("custom_colors", image.customColors)
    image.dpi = obj.get("dpi", image.dpi)
    image.clipColors = obj.get("clip_colors", image.clipColors)
    if "resolution" in obj:
        image.resolution = list(obj["resolution"])
    if image.customColors is not None:
        image.customColors = np.array(image.customColors)
        if image.colorscheme == Colorschemes.CUSTOM:
            image.colorscheme.update(image.customColors)


def _imagesettings_to_json(img_id: int, im: ImageSettings) -> dict[str, Any]:
    def element_to_json(element, channel_key, overridden):
        return {
            "ref": _ref_to_json(element.ref),
            "channel_key": channel_key,
            "override": _elementsettings_to_json(element) if overridden else None,
        }

    elements = {}
    for slot, es in im.elements.items():
        elements[str(slot)] = element_to_json(
            es, im.channel_keys[slot], slot in im.element_overrides
        )
    return {
        "id": img_id,
        "name": im.name,
        "sample_id": im.sample_id,
        "sample_source_ids": list(
            im.sample_source_ids
            or sorted(
                {es.ref.source_id for es in im.elements.values()}
                | {
                    element.ref.source_id
                    for element, _key, _overridden in im.suspended_elements.values()
                }
            )
        ),
        **_image_options_to_json(im),
        "elements": elements,
    }


def _imagesettings_from_json(obj: dict[str, Any], project_data: ProjectData) -> ImageSettings:
    """Restore an image, omitting slots whose source is absent from the model."""
    sample_source_ids = obj.get("sample_source_ids", ())
    sample_id = obj["sample_id"]
    if sample_id not in project_data.samples:
        raise ValueError(f"Image {obj['name']!r} refers to an unknown sample")
    im = ImageSettings(obj["name"], sample_id=sample_id, sample_source_ids=sample_source_ids)
    _apply_image_options(im, obj)

    def restore_element(slot_s, es_obj, *, suspended):
        slot = int(slot_s)
        ref = ElementRef.from_json(es_obj["ref"])

        fs = project_data.sources.get(ref.source_id)
        if fs is None:
            return

        asset = project_data.assets.get(ref.source_id)
        if asset is None or asset.sample_id != im.sample_id:
            raise ValueError(f"Image {im.name!r} contains a map outside its sample")

        key = es_obj["channel_key"]
        if key is None:
            _sample, channel = project_data.channel_for_ref(ref)
            key = channel.key
        override = es_obj["override"]
        if override is not None:
            es = _elementsettings_from_json(ref, fs, project_data.element_defaults, override)
            overridden = True
        else:
            es = project_data.element_settings.get(ref)
            if es is None:
                raise ValueError(f"Image {im.name!r} refers to settings that were not saved")
            overridden = False

        if suspended:
            im.suspended_elements[slot] = (es, key, overridden)
        else:
            im.elements[slot] = es
            im.channel_keys[slot] = key
            if overridden:
                im.element_overrides.add(slot)

    for slot_s, es_obj in obj.get("elements", {}).items():
        restore_element(slot_s, es_obj, suspended=False)

    return im


def _candidate_to_json(candidate):
    result = candidate.result
    obj = {
        "sample_id": result.sample_id,
        "method_id": result.method_id,
        "input_ref": _ref_to_json(result.input_ref),
        "model_id": result.output.model_id,
        "model_version": result.output.model_version,
        "parameters": {
            "clip_percentile": result.parameters.clip_percentile,
            "method_options": dict(result.parameters.method_options),
        },
        "layer_settings": _layer_settings_to_json(result.layer_settings),
        "postprocessing": {
            "minimum_area": result.postprocessing.minimum_area,
            "expansion": result.postprocessing.expansion,
        },
        "reference_refs": [_ref_to_json(ref) for ref in result.reference_refs],
        "sidecar": str(
            candidate_relative_path(result.sample_id, candidate.candidate_id, candidate.revision_id)
        ),
    }
    obj.update(
        candidate_id=candidate.candidate_id,
        revision_id=candidate.revision_id,
        name=candidate.name,
        name_is_custom=candidate.name_is_custom,
        created_at=candidate.created_at,
        parent_id=candidate.parent_id,
        keep=candidate.keep,
        edited=candidate.edited,
        reviewed_revision=candidate.reviewed_revision,
        compare=candidate.compare,
        comparison_presentation=(
            None
            if candidate.comparison_presentation is None
            else asdict(candidate.comparison_presentation)
        ),
        provenance=[
            {
                "run_id": run.run_id,
                "created_at": run.created_at,
                "method_id": run.method_id,
                "input_ref": _ref_to_json(run.input_ref),
                "parameters": {
                    "clip_percentile": run.parameters.clip_percentile,
                    "method_options": run.parameters.method_options,
                },
                "model_id": run.model_id,
                "model_version": run.model_version,
            }
            for run in candidate.provenance
        ],
    )
    return obj


def save_segmentation_snapshots(project_data, project_dir):
    """Ensure referenced immutable snapshots exist before publishing JSON."""
    for history in project_data.segmentation_histories.values():
        for candidate in history.candidates.values():
            save_candidate(candidate, project_dir)
    for session in project_data.segmentation_edit_sessions.values():
        if session.changed:
            save_candidate(session.snapshot(), project_dir)


def export_project_state(
    project_data: ProjectData, project_dir: str | Path | None = None
) -> dict[str, Any]:
    """Build a JSON-serializable state dictionary from ``ProjectData``."""
    assets = []
    project_data.update_external_data_root(project_dir)
    for asset_id, asset in sorted(project_data.assets.items()):
        sample = project_data.samples[asset.sample_id]
        channels = [
            {
                "key": channel.key,
                "name": channel.name,
                "item_id": channel.ref.item_id,
            }
            for channel in sorted(sample.channels.values(), key=lambda value: value.key)
            if channel.ref is not None and channel.ref.source_id == asset_id
        ]
        assets.append(
            {
                "asset_id": asset_id,
                "path": asset_path_to_json(asset, project_dir, project_data.external_data_root),
                "original_path": asset.original_path,
                "alias": asset.source.alias,
                "kind": asset.source.kind,
                "sample_id": sample.sample_id,
                "channels": channels,
            }
        )

    samples = []
    for sample in sorted(project_data.samples.values(), key=lambda value: value.sample_id):
        overrides = {}
        for key, override in sorted(sample.channel_overrides.items()):
            overrides[key] = (
                None
                if override is None
                else {
                    "name": override.name,
                    "settings_ref": _settings_ref_to_json(override.settings),
                }
            )
        samples.append(
            {
                "id": sample.sample_id,
                "name": sample.name,
                "shape": list(sample.shape) if sample.shape is not None else None,
                "channel_overrides": overrides,
            }
        )

    element_settings = [
        _elementsettings_to_json(es)
        for _ref, es in sorted(project_data.element_settings.items(), key=lambda pair: pair[0])
    ]
    project_channels = [
        {
            "key": channel.key,
            "name": channel.name,
            "settings_ref": _settings_ref_to_json(channel.settings),
        }
        for channel in sorted(project_data.project_channels.values(), key=lambda value: value.key)
    ]

    images = []
    for img_id, im in sorted(project_data.images.items()):
        images.append(_imagesettings_to_json(img_id, im))

    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "element_defaults": project_data.element_defaults.to_json(),
        "abundance_units": project_data.abundance_units,
        "segmentation_method": project_data.segmentation_method,
        "image_defaults": _image_options_to_json(
            project_data.image_defaults, include_resolution=True
        ),
        "external_data_root": project_data.external_data_root,
        "samples": samples,
        "assets": assets,
        "project_channels": project_channels,
        "element_settings": element_settings,
        "images": images,
        "segmentation_histories": [
            {
                "sample_id": sample_id,
                "active_id": history.active_id,
                "recent_limit": history.recent_limit,
                "recency": list(history.recency),
                "candidates": [
                    _candidate_to_json(candidate) for candidate in history.candidates.values()
                ],
            }
            for sample_id, history in sorted(project_data.segmentation_histories.items())
        ],
        "segmentation_drafts": [
            {
                "sample_id": sample_id,
                "source_id": session.source.candidate_id,
                "pending_disconnections": sorted(session.pending_disconnections),
                "candidate": _candidate_to_json(session.snapshot()),
            }
            for sample_id, session in sorted(project_data.segmentation_edit_sessions.items())
            if session.changed
        ],
        "segmentation_previews": [
            {
                "sample_id": sample_id,
                "method_id": method_id,
                "input_ref": None if preview.input_ref is None else _ref_to_json(preview.input_ref),
                "reference_refs": [_ref_to_json(ref) for ref in preview.reference_refs],
                "layer_settings": _layer_settings_to_json(preview.layer_settings),
            }
            for sample_id, previews in sorted(project_data.segmentation_previews.items())
            for method_id, preview in sorted(previews.items())
        ],
        "clustering_results": [
            {
                "sample_id": result.sample_id,
                "element_refs": [_ref_to_json(ref) for ref in result.element_refs],
                "parameters": {"min_k": result.parameters.min_k, "max_k": result.parameters.max_k},
                "layer_settings": _layer_settings_to_json(result.layer_settings),
                "sidecar": str(clustering_relative_path(result.sample_id)),
            }
            for result in sorted(
                project_data.clustering_results.values(), key=lambda result: result.sample_id
            )
        ],
        "matrix_plots": {
            key: settings.to_json()
            for key, settings in sorted(project_data.matrix_plot_settings.items())
        },
        "matrix_publication": project_data.matrix_publication_settings.to_json(),
    }


def validate_project_state(state: dict[str, Any]) -> None:
    """Check the project header before replacing the current project."""
    if not isinstance(state, dict):
        raise ValueError("Project data must be a JSON object")
    if state.get("format") != PROJECT_FORMAT:
        raise ValueError(f"Not an {PROJECT_FORMAT!r} file")
    version = state.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"Invalid project version {version!r}")
    if version > PROJECT_VERSION:
        raise ValueError(
            f"Project version {version} is newer than supported version {PROJECT_VERSION}"
        )
    for field in ("samples", "assets"):
        if not isinstance(state.get(field), list):
            raise ValueError(f"Project has no usable {field!r} list")


def save_project(project_data: ProjectData, filename: str | Path) -> None:
    """Write missing immutable snapshots, then atomically publish project metadata."""
    filename = Path(filename)
    save_segmentation_snapshots(project_data, filename.parent)
    save_project_state(export_project_state(project_data, filename.parent), filename)


def save_project_state(state: dict[str, Any], filename: str | Path) -> None:
    """Atomically write an already exported project state."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        temporary = create_staging_file(filename.parent, prefix=f".{filename.name}.")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def load_project_state(
    project_data: ProjectData,
    state: dict[str, Any],
    *,
    open_files: bool = True,
    project_dir: str | Path | None = None,
) -> list[str]:
    """Restore saved state into an empty ``ProjectData`` model.

    Return recoverable loading issues. Missing data files retain their saved
    channel identities so the user can relocate them after opening the project.
    """
    validate_project_state(state)

    issues = []
    method = state.get("segmentation_method")
    if method is None or isinstance(method, str):
        project_data.segmentation_method = method
    else:
        issues.append("Segmentation method selection was reset: expected a string")
    abundance_units = state.get("abundance_units", project_data.abundance_units)
    if isinstance(abundance_units, str):
        project_data.abundance_units = abundance_units
    else:
        issues.append("Element abundance units were reset: expected a string")
    try:
        project_data.element_defaults = ElementSettingsDefaults.from_json(
            state.get("element_defaults", ElementSettingsDefaults().to_json())
        )
    except (KeyError, TypeError, ValueError) as exc:
        project_data.element_defaults = ElementSettingsDefaults()
        issues.append(f"Element defaults were reset: {exc}")
    try:
        _apply_image_options(project_data.image_defaults, state.get("image_defaults", {}))
    except (KeyError, TypeError, ValueError) as exc:
        project_data.image_defaults = ImageSettings("")
        issues.append(f"Image defaults were reset: {exc}")
    matrix_plots = state.get("matrix_plots", {})
    if not isinstance(matrix_plots, dict):
        matrix_plots = {}
        issues.append("Matrix plot settings were reset: expected an object")
    for key, settings in project_data.matrix_plot_settings.items():
        settings.reset()
        try:
            plot_state = matrix_plots.get(key, {})
            if not isinstance(plot_state, dict):
                raise TypeError("expected an object")
            settings.apply_json(plot_state)
        except (TypeError, ValueError) as exc:
            settings.reset()
            issues.append(f"{key.replace('_', ' ').title()} settings were reset: {exc}")
    project_data.matrix_publication_settings.reset()
    try:
        publication_state = state.get("matrix_publication", {})
        if not isinstance(publication_state, dict):
            raise TypeError("expected an object")
        project_data.matrix_publication_settings.apply_json(publication_state)
    except (TypeError, ValueError) as exc:
        project_data.matrix_publication_settings.reset()
        issues.append(f"Matrix publication settings were reset: {exc}")

    # Samples and assets
    external_data_root = state.get("external_data_root")
    project_data.external_data_root = external_data_root
    filenames = [
        asset_path_from_json(asset["path"], project_dir, external_data_root)
        for asset in state["assets"]
    ]
    for sample_obj in state["samples"]:
        sample = project_data.create_sample(sample_obj["name"], sample_obj["id"])
        shape = sample_obj.get("shape")
        sample.shape = tuple(shape) if shape is not None else None
    if open_files:
        for filename, asset_obj in zip(filenames, state["assets"], strict=True):
            source = None
            try:
                source = open_source(filename)
                source.source_id = asset_obj["asset_id"]
                source.alias = asset_obj["alias"]
                project_data.register_source(
                    source,
                    sample_id=asset_obj["sample_id"],
                    channel_names={
                        channel["item_id"]: (channel["key"], channel["name"])
                        for channel in asset_obj["channels"]
                    },
                )
                project_data.assets[asset_obj["asset_id"]].original_path = asset_obj[
                    "original_path"
                ]
            except Exception as exc:
                if source is not None and source.is_open:
                    source.close()
                source = LoadedSource(
                    asset_obj["asset_id"],
                    filename,
                    asset_obj["alias"],
                    asset_obj["kind"],
                    open_error=f"{type(exc).__name__}: {exc}",
                )
                project_data.register_unavailable_source(
                    source,
                    sample_id=asset_obj["sample_id"],
                    channels=asset_obj["channels"],
                    shape=project_data.samples[asset_obj["sample_id"]].shape,
                    original_path=asset_obj["original_path"],
                )
                issues.append(f"Data file {filename!r} could not be opened: {source.open_error}")

    for filename, asset_obj in zip(filenames, state["assets"], strict=True):
        asset_id = asset_obj["asset_id"]
        if asset_id in project_data.sources:
            project_data.sources[asset_id].alias = asset_obj["alias"]
            project_data.assets[asset_id].path = filename

    # Element settings
    for settings_obj in state.get("element_settings", []):
        try:
            ref = ElementRef.from_json(settings_obj["ref"])
            fs = project_data.sources.get(ref.source_id)
            if fs is None:
                continue
            project_data.set_element_settings(
                ref,
                _elementsettings_from_json(ref, fs, project_data.element_defaults, settings_obj),
            )
        except Exception as exc:
            issues.append(f"One element's settings were skipped: {exc}")

    settings_by_ref = project_data.element_settings
    for sample in project_data.samples.values():
        for channel in sample.channels.values():
            channel.settings = settings_by_ref.get(channel.ref)

    # Project channels and sample-local decisions
    for channel_obj in state.get("project_channels", []):
        try:
            project_data.add_project_channel(
                channel_obj["key"],
                channel_obj.get("name"),
                _settings_from_ref(channel_obj.get("settings_ref"), settings_by_ref),
            )
        except Exception as exc:
            issues.append(f"One project element selection was skipped: {exc}")
    for sample_obj in state["samples"]:
        sample = project_data.samples[sample_obj["id"]]
        for key, override_obj in sample_obj.get("channel_overrides", {}).items():
            try:
                sample.channel_overrides[key] = (
                    None
                    if override_obj is None
                    else ChannelOverride(
                        name=override_obj.get("name"),
                        settings=_settings_from_ref(
                            override_obj.get("settings_ref"), settings_by_ref
                        ),
                    )
                )
            except Exception as exc:
                issues.append(f"A sample element override was skipped: {exc}")
    for iobj in state.get("images", []):
        try:
            img_id = iobj["id"]
            im = _imagesettings_from_json(iobj, project_data)
            im.resolution = list(project_data.image_defaults.resolution)
            sample = project_data.samples[im.sample_id]
            im.reconcileChannels(sample.effective_channels(project_data.project_channels))
            project_data.images[img_id] = im
        except Exception as exc:
            name = iobj.get("name", "unnamed") if isinstance(iobj, dict) else "invalid"
            issues.append(f"Image {name!r} was skipped: {exc}")

    # Segmentation results are independent derived objects. A damaged or
    # missing sidecar must not prevent the rest of the project from loading.
    if project_dir is not None:
        for obj in state.get("segmentation_previews", []):
            try:
                sample = project_data.samples[obj["sample_id"]]
                available = {channel.ref for channel in sample.channels.values()}
                input_ref = ElementRef.from_json(obj["input_ref"]) if obj.get("input_ref") else None
                project_data.segmentation_previews.setdefault(sample.sample_id, {})[
                    obj["method_id"]
                ] = SegmentationPreview(
                    input_ref=input_ref if input_ref in available else None,
                    reference_refs=tuple(
                        ref
                        for value in obj.get("reference_refs", [])
                        if (ref := ElementRef.from_json(value)) in available
                    ),
                    layer_settings=_layer_settings_from_json(obj.get("layer_settings")),
                )
            except Exception as exc:
                issues.append(f"One segmentation preview was skipped: {exc}")

        history_objects = state.get("segmentation_histories")
        pending = {}
        if history_objects is None:
            result_objects = state.get("segmentation_results", [])
        else:
            result_objects = []
            for history_obj in history_objects:
                try:
                    sample_id = history_obj["sample_id"]
                    if sample_id not in project_data.samples:
                        raise ValueError("sample no longer exists")
                    pending[sample_id] = (history_obj, [])
                    result_objects.extend(
                        {**obj, "sample_id": sample_id} for obj in history_obj.get("candidates", [])
                    )
                except Exception as exc:
                    issues.append(f"One segmentation history was skipped: {exc}")
        drafts = []
        if history_objects is not None:
            for draft in state.get("segmentation_drafts", []):
                try:
                    result_objects.append(
                        {
                            **draft["candidate"],
                            "sample_id": draft["sample_id"],
                            "_draft_source": draft["source_id"],
                            "_pending_disconnections": draft.get("pending_disconnections", []),
                        }
                    )
                except Exception as exc:
                    issues.append(f"One working mask was skipped: {exc}")
        for result_obj in result_objects:
            try:
                sample_id = result_obj["sample_id"]
                method_id = result_obj.get("method_id", "stardist")
                sample = project_data.samples[sample_id]
                input_ref = ElementRef.from_json(
                    result_obj.get("input_ref", result_obj.get("nuclei_ref"))
                )
                if input_ref not in {channel.ref for channel in sample.channels.values()}:
                    raise ValueError("input element map no longer belongs to the sample")
                parameter_values = result_obj.get("parameters", {})
                options = dict(parameter_values.get("method_options", {}))
                options.pop("model_path", None)
                parameters = SegmentationParameters(
                    clip_percentile=parameter_values.get("clip_percentile"),
                    method_options=options,
                )
                sidecar = Path(project_dir) / result_obj["sidecar"]
                try:
                    layer_settings = _layer_settings_from_json(result_obj.get("layer_settings"))
                except Exception as exc:
                    layer_settings = SegmentationLayerSettings()
                    issues.append(f"Segmentation layer presentation was ignored: {exc}")
                result = SegmentationResult(
                    sample_id=sample_id,
                    method_id=method_id,
                    input_ref=input_ref,
                    parameters=parameters,
                    output=load_segmentation(
                        sidecar,
                        expected_method_id=method_id,
                        candidate_id=result_obj.get("candidate_id"),
                        revision_id=result_obj.get("revision_id"),
                    ),
                    layer_settings=layer_settings,
                    postprocessing=SegmentationPostprocessing(
                        result_obj.get("postprocessing", {}).get("minimum_area", 0),
                        expansion=result_obj.get("postprocessing", {}).get("expansion", 0),
                    ),
                    reference_refs=tuple(
                        ref
                        for value in result_obj.get("reference_refs", [])
                        if (ref := ElementRef.from_json(value))
                        in {channel.ref for channel in sample.channels.values()}
                    ),
                )
                if history_objects is None:
                    project_data.set_segmentation_result(result)
                else:
                    provenance = tuple(
                        SegmentationRun(
                            method_id=run["method_id"],
                            input_ref=ElementRef.from_json(run["input_ref"]),
                            parameters=SegmentationParameters(**run["parameters"]),
                            model_id=run["model_id"],
                            model_version=run["model_version"],
                            run_id=run["run_id"],
                            created_at=run["created_at"],
                        )
                        for run in result_obj.get("provenance", [])
                    )
                    fields = {
                        name: result_obj[name]
                        for name in (
                            "candidate_id",
                            "revision_id",
                            "name",
                            "name_is_custom",
                            "created_at",
                            "parent_id",
                            "keep",
                            "edited",
                            "reviewed_revision",
                            "compare",
                        )
                        if name in result_obj
                    }
                    candidate = SegmentationCandidate(
                        result, provenance or (SegmentationRun.from_result(result),), **fields
                    )
                    if result_obj.get("comparison_presentation") is not None:
                        candidate.comparison_presentation = _layer_settings_from_json(
                            {"layers": {"mask": result_obj["comparison_presentation"]}}
                        ).layers.get("mask")
                    if "_draft_source" in result_obj:
                        drafts.append(
                            (
                                sample_id,
                                result_obj["_draft_source"],
                                candidate,
                                result_obj.get("_pending_disconnections", []),
                            )
                        )
                    else:
                        pending[sample_id][1].append(candidate)
            except Exception as exc:
                issues.append(f"One segmentation result was skipped: {exc}")
        for sample_id, (obj, candidates) in pending.items():
            try:
                history, errors = SegmentationHistory.restore(
                    sample_id,
                    candidates,
                    active_id=obj.get("active_id"),
                    recency=obj.get("recency", ()),
                    recent_limit=obj.get("recent_limit", 5),
                )
                project_data.segmentation_histories[sample_id] = history
                issues.extend(errors)
            except Exception as exc:
                issues.append(f"One segmentation history was skipped: {exc}")
        for sample_id, source_id, draft, pending_disconnections in drafts:
            try:
                history = project_data.segmentation_histories[sample_id]
                source = history.candidates[source_id]
                project_data.segmentation_edit_sessions[sample_id] = (
                    SegmentationEditSession.restore(source, draft, pending=pending_disconnections)
                )
                history.activate(source_id)
            except Exception as exc:
                issues.append(f"One working mask was skipped: {exc}")

    if project_dir is not None:
        for obj in state.get("clustering_results", []):
            try:
                sample = project_data.samples[obj["sample_id"]]
                refs = tuple(ElementRef.from_json(ref) for ref in obj["element_refs"])
                if not set(refs) <= {channel.ref for channel in sample.channels.values()}:
                    raise ValueError("input element maps no longer belong to the sample")
                parameters = ClusteringParameters(**obj["parameters"])
                try:
                    layer_settings = _layer_settings_from_json(obj.get("layer_settings"))
                except Exception as exc:
                    layer_settings = SegmentationLayerSettings()
                    issues.append(f"Element-cluster layer presentation was ignored: {exc}")
                result = ClusteringResult(
                    sample.sample_id,
                    refs,
                    parameters,
                    load_xrf_sample(
                        Path(project_dir) / obj["sidecar"], expected_method_id="element-clusters"
                    ),
                    layer_settings,
                )
                project_data.clustering_results[sample.sample_id] = result
            except Exception as exc:
                issues.append(f"One element-clustering result was skipped: {exc}")

    return issues


def load_project(
    project_data: ProjectData, filename: str | Path, *, open_files: bool = True
) -> list[str]:
    """Read project JSON and restore it into an empty model."""

    filename = Path(filename)
    with filename.open("r", encoding="utf-8") as f:
        state = json.load(f)
    return load_project_state(
        project_data, state, open_files=open_files, project_dir=filename.parent
    )
