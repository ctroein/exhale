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
`ProjectManager` owns project-directory operations, `SourceManager` owns
source-file import, closure, removal, and relocation, and `ProjectStateManager`
owns dirty-state, autosave, and recovery policy.
`AnalysisController` owns Segmentation-tab selection, execution, result
display, and export, including its worker and Napari state.
`ElementController` owns Element maps selection, effective channel
presentation, transformation controls, and single-map display.
`ImageController` owns composed-image selection, slot and override editing,
presentation controls, canvas mapping, and export. Dialog classes translate
between focused groups of controls and their settings objects. `NapariHelper`,
`ImageCanvas`, `ImageComposer`, and the layer widgets own their respective
visualization concerns.

## Project and channel model

Widget-independent models and source handling live in `exhale.data`. This
package must not import Qt widgets or application controllers.

`ProjectData` is the authoritative owner of loaded assets, samples,
composed-image settings, project-level channel selection, per-sample channel
overrides, segmentation results, and shared defaults. A `DataAsset` represents
a physical source file; a `Sample` groups compatible channel maps; and a
`Channel` describes one map within that sample.

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

`ElementController` presents and edits those settings without owning a second
model copy. Its current selection and editor context are controller UI state;
they are not mirrored on `MainWindow`.

## Source loading and import

`exhale.data.source_refs` detects HDF5 and TIFF files by content, validates
that their maps are nonempty two-dimensional numeric arrays, and owns the
underlying file handles. `exhale.data.tiffimport` makes conservative, editable
sample and channel-name suggestions from TIFF filenames; it does not determine
semantic identity.

All channels in one sample must have compatible shapes. `ProjectData` performs
that validation when an asset is added or replaced and prevents duplicate
channel keys within a sample.

`SourceManager` is the application boundary around those model operations. It
opens and closes file handles, coordinates source removal or relocation, and
refreshes the controllers affected by a successful change. `MainWindow` only
wires source actions to that manager and supplies application-level dialogs.

## Images and visualization

Image composition, display, and image-specific controls live in
`exhale.imaging`.

`ImageComposer` converts selected element maps and their `ImageSettings` into
an exact RGBA canvas. `ComposedImageMapping` maps displayed pixels back to the
merged source coordinates. `ImageCanvas` displays arrays without changing
their numeric meaning and reports interaction coordinates in array space.

`ImageController` owns the current composed-image selection and its disposable
composer and canvas state. Saved `ImageSettings` remain in `ProjectData`; the
selection is not mirrored on `MainWindow`.

Napari is isolated behind `NapariHelper`. `LayerListWidget` and
`LayerRowWidget` expose the presentation state of embedded layers without
becoming an alternative owner of the layer data. Re-entering the Segmentation
tab retains an unchanged result view; changed element transformations replace
only the corresponding image-layer data.

## Analysis and derived results

Analysis execution, persistence, and result visualization live in
`exhale.analysis`. The numerical implementation in `xrf_refcopy/` is imported
external code and remains a separate boundary.

`AnalysisWorker` runs XRF analysis away from the GUI thread, translates Python
and native-library output into progress messages, and supports cooperative
abortion. `AnalysisController` owns the worker and thread lifetime and all
Segmentation-tab UI state; the main window only constructs the controller and
passes application-level changes to it. The classes under `xrf_refcopy/`
implement nuclei segmentation, tissue masking, intensity partitioning,
per-element clustering, and combined sample tables.

Completed analysis is represented by `SegmentationResult` in the project
model. The large arrays and result tables are stored separately by
`exhale.analysis.segmentationio` in an HDF5 sidecar below the project; the main
project file stores the association and parameters.

## Persistence and state changes

Saved-project persistence, lifecycle policy, and project controls live in
`exhale.project`. `exhale.project.projectio` is the only module which
translates the live project graph to and from the JSON project representation.
It accepts `ProjectData` rather than a window and does not update widgets or
emit GUI signals. `ProjectManager` performs the coordinated post-load UI
refresh. Paths are stored with relocatable forms where possible. Loading is
structurally tolerant according to the policy in
[`development.md`](development.md), but core project identity and sample/asset
structure remain mandatory.

`ProjectStateManager` compares a canonical serialized snapshot with the last
saved or loaded state. It schedules autosaves, handles recovery data, and
guards project replacement when unsaved work exists. `ProjectManager` handles
directory selection and delegates serialization and dirty-state decisions to
the appropriate modules. `SourceManager` handles the independent lifecycle of
the data files referenced by the project.

Application-wide window state is separate from project data. `QSettings`
stores the window geometry, active tab, and all five main-window splitter
layouts. Splitters restore only after their containing tab has usable geometry
and are saved only after they have been initialized. A saved layout containing
a completely collapsed pane is discarded in favor of the default proportions
so application state cannot make a panel effectively disappear on restart.

## Ownership rules

Mutable semantic state has one owner. Widgets display or edit it but must not
maintain independent authoritative copies. File-backed caches, composed
images, histograms, Napari layers, and formatted result tables are derived and
disposable.

Errors caused by user data should identify the affected source or operation
and remain recoverable where the rest of a project is usable. Programming
errors should fail clearly rather than being converted into plausible but
incorrect state.
