# Exhale architecture

This document describes the durable structure of Exhale. The file-by-file
index is in [`code-overview.md`](code-overview.md), while enforceable coding
and documentation conventions are in [`development.md`](development.md).

## Application structure

Exhale is a Qt desktop application for organizing X-ray fluorescence maps,
configuring their presentation, composing publication images, and running
cell-segmentation and clustering analysis. `exhale.__main__` creates the Qt
application and `MainWindow`; `MainWindow` owns the application shell and
wires the feature-specific objects together.

Qt is accessed through `qtpy`. Layouts are authored in Qt Designer `.ui`
files. The corresponding `*_ui.py` modules are generated build products and
contain no application policy.

Large workflows should have a coherent owner rather than accumulating in the
window. `ProjectTab` coordinates project and sample controls,
`ProjectManager` owns project-directory operations, and
`ProjectStateManager` owns dirty-state, autosave, and recovery policy. Dialog
classes translate between focused groups of controls and their settings
objects. `NapariHelper`, `ImageCanvas`, `ImageComposer`, and the layer widgets
own their respective visualization concerns.

## Project and channel model

Widget-independent models and source handling live in `exhale.data`. This
package must not import Qt widgets or application controllers.

`ProjectData` is the authoritative owner of loaded assets, samples,
project-level channel selection, per-sample channel overrides, segmentation
results, and shared defaults. A `DataAsset` represents a physical source file;
a `Sample` groups compatible channel maps; and a `Channel` describes one map
within that sample.

`ElementRef` is the stable identity of a map: it combines a source identity
with an item identity inside that source. HDF5 dataset paths and TIFF
page/component identifiers remain storage details behind this common value.
Raw filename/dataset tuples must not become a second identity system.

`ChannelData` separates access to a two-dimensional map from its storage.
`ArrayChannelData` owns an already-materialized NumPy array, while
`SourceChannelData` reads through an open `LoadedSource` and may retain a
disposable array cache. Closing a source invalidates uncached file-backed data
but does not invalidate arrays which have already been materialized.

`ElementSettings` contains display and normalization settings for a channel.
Project and sample resolution determines the effective settings. An image slot
normally refers to those effective settings; only an explicit image override
owns a copy. `ImageSettings` records the distinction so propagation is not
inferred from object identity alone.

## Source loading and import

`exhale.data.source_refs` detects HDF5 and TIFF files by content, validates
that their maps are nonempty two-dimensional numeric arrays, and owns the
underlying file handles. `exhale.data.tiffimport` makes conservative, editable
sample and channel-name suggestions from TIFF filenames; it does not determine
semantic identity.

All channels in one sample must have compatible shapes. `ProjectData` performs
that validation when an asset is added or replaced and prevents duplicate
channel keys within a sample.

## Images and visualization

`ImageComposer` converts selected element maps and their `ImageSettings` into
an exact RGBA canvas. `ComposedImageMapping` maps displayed pixels back to the
merged source coordinates. `ImageCanvas` displays arrays without changing
their numeric meaning and reports interaction coordinates in array space.

Napari is isolated behind `NapariHelper`. `LayerListWidget` and
`LayerRowWidget` expose the presentation state of embedded layers without
becoming an alternative owner of the layer data.

## Analysis and derived results

`AnalysisWorker` runs XRF analysis away from the GUI thread, translates Python
and native-library output into progress messages, and supports cooperative
abortion. The classes under `xrf_refcopy/` implement nuclei segmentation,
tissue masking, intensity partitioning, per-element clustering, and combined
sample tables.

Completed analysis is represented by `SegmentationResult` in the project
model. The large arrays and result tables are stored separately by
`segmentationio` in an HDF5 sidecar below the project; the main project file
stores the association and parameters.

## Persistence and state changes

`projectio` is the only module which translates the live project graph to and
from the JSON project representation. Paths are stored with relocatable forms
where possible. Loading is structurally tolerant according to the policy in
[`development.md`](development.md), but core project identity and sample/asset
structure remain mandatory.

`ProjectStateManager` compares a canonical serialized snapshot with the last
saved or loaded state. It schedules autosaves, handles recovery data, and
guards project replacement when unsaved work exists. `ProjectManager` handles
directory selection and delegates serialization and dirty-state decisions to
the appropriate modules.

## Ownership rules

Mutable semantic state has one owner. Widgets display or edit it but must not
maintain independent authoritative copies. File-backed caches, composed
images, histograms, Napari layers, and formatted result tables are derived and
disposable.

Errors caused by user data should identify the affected source or operation
and remain recoverable where the rest of a project is usable. Programming
errors should fail clearly rather than being converted into plausible but
incorrect state.
