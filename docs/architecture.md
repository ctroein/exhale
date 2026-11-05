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
`CorrelationController` owns the independent Relationships subtabs, their
disposable numerical results, session caching, and result presentation.
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
Matrix palette definitions also live there, so project settings and renderers
use one palette catalog.

`ProjectData` is the authoritative owner of loaded assets, samples,
composed-image settings, project-level channel selection, per-sample channel
overrides, segmentation results, and shared defaults. A `DataAsset` represents
a physical source file; a `Sample` groups compatible channel maps; and a
`Channel` describes one map within that sample.

`ElementRef` is the stable identity of a map: it combines a source identity
with an item identity inside that source. HDF5 dataset paths and TIFF
page/component identifiers remain storage details behind this common value.
Raw filename/dataset tuples must not become a second identity system.
The source identity is initially its absolute path and remains unchanged when
the backing file is relocated; `LoadedSource.filename` records the current path.

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
For a sample channel, an absent override inherits the project selection, a
`None` override skips it, and a `ChannelOverride` explicitly selects local
settings. A channel without a project selection is absent unless overridden.

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
only the corresponding image-layer data. Shared initial fitting follows actual
canvas geometry while startup layouts settle, ending on canvas interaction or
leaving the view. Opening a new project resets this first-display fitting.

## Analysis and derived results

Analysis execution, persistence, and result visualization live in
`exhale.analysis`. The remaining element-clustering and legacy region-table implementation in
`xrf_refcopy/` stays behind a separate boundary. Its former neural inference and
combined processing entry points have been removed.

Batch segmentation uses a separate `SegmentationBatchController` owned by
`AnalysisController`. The review dialog captures checked samples and their nuclei
channels; method/options are snapshotted when starting the batch. Samples with
an existing run of that method are skipped by default. The queue is session-only.
One `BatchSegmentationWorker` loads and segments maps sequentially in a background
thread and publishes each completed output through GUI-thread callbacks. Model
acquisition and loaded model caches are reused. Individual failures are collected
while other samples continue; a shared model-acquisition failure stops the queue.

`publish_segmentation(..., activate=False)` saves an immutable candidate while
retaining the sample's current active mask. Working edits and viewer selection
are preserved; first results can be shown for the already-viewed empty sample.
Batch inference locks run/method/options controls while leaving inspection and
editing available. Stop cooperatively cancels current inference and the remaining
queue, keeping published masks. Clearing or closing a project invalidates queued
callbacks and waits for cancellation before source handles are closed. Current
backend calls may finish before cancellation takes effect. Element clustering
cannot run concurrently with either single or batch segmentation.

The lightweight segmentation-method registry supplies stable method IDs,
dependency checks and worker factories without importing numerical backends.
`AnalysisWorker` accepts a private snapshot of one map and returns a
`SegmentationOutput`: validated uint32 instance labels and model identity/version.
It never constructs an `XRFSample`, computes tissue masks, filters instances by
intensity or generates membranes. StarDist calls our direct adapter, preserving
its `predict_instances()` labels; Cellpose uses its own instance reconstruction
with training-matched 0–100 percentile normalization. Upper-percentile clipping
is an internal method parameter. There is no spatial resampling.

`segmentation_backends` initializes PyTorch and Triton before TensorFlow and
requests TensorFlow GPU memory growth, only when segmentation is first run.
This avoids the tested native LLVM/CUDA loading-order conflicts. Model caching
avoids repeated loading; provenance hashes include the trained weights and, for
StarDist, its architecture and inference thresholds.

`SegmentationResult` associates the output with one input reference, sample,
method, parameter snapshot and layer settings. Segmentation sidecars contain only
labels and model provenance; project JSON contains the reference and run settings.
The sidecar retains the original method output. Project-owned post-processing
settings derive a cached label image without renumbering surviving instances;
display, inspection and statistics use that processed image. Mask export uses
the selected candidate or working edits before post-processing.
Changing the minimum pixel area invalidates the derived cache but does not rewrite
the sidecar. Cached areas and labels are omitted from project state.
Optional reference-map selections and presentation are saved per sample/method.
Before a first successful run, `SegmentationPreview` retains inspection state;
successful output takes over that state and removes the preview entry.
Structurally usable existing nested label datasets load directly without
constructing the legacy model. A failed write leaves the previous sidecar intact;
failed or cancelled workers never replace the project's successful result.

Downstream mask inputs use immutable `data.segmentationref.SegmentationReference`
records containing sample, candidate, revision and post-processing settings.
`ProjectData.segmentation_reference()` captures an accepted candidate; draft edits
are not downstream inputs. Consumers persist `reference.to_json()` with their
own output and reconstruct it with `SegmentationReference.from_json()`.
`segmentation_reference_is_current(reference, candidate_id)` compares with the
consumer's explicitly chosen input. Changed label identity or processing, and
missing inputs, make results outdated. Status is derived, so restoring the exact
input makes results current again. Names, colors, review state, added provenance
and viewer selection do not invalidate numerical results. No check automatically
replaces or recomputes consumer output.

`resolve_segmentation_reference()` returns read-only labels using the recorded
processing settings even if current controls differ. A missing exact revision
raises an unavailable-input error; it never substitutes a newer or active mask.
References do not pin candidates in history; removal or pruning can make an input
unavailable. Future consumers must decide their retention policy when introduced.
Element clustering and cluster-distance results remain segmentation-independent;
no segmentation reference fields or controls are added to them in this stage.

The sample-level candidate model is defined in `data.segmentationhistory` and
owned by `ProjectData.segmentation_histories`. Each candidate owns a snapshot of
labels and mutable presentation/settings, with candidate/revision IDs, name,
parent ID, creation time, Keep/edit flags and revision-specific review state.
Inference events independently record method, model, input reference, parameters
and run identity/time. Identical partitions reuse a candidate even when label IDs
differ; provenance accumulates without replacing its name, corrections or review.
Five recent unprotected candidates are retained, together with active, kept,
edited and reviewed masks. Ancestors needed by retained candidates are preserved.
Selecting a candidate changes neither candidate ordering nor inference recency.

Candidate history is now the authoritative store and is serialized in project
JSON, including active identity, retention order, run provenance, review and
presentation state. Labels live in immutable sample/candidate/revision sidecars.
Publication writes a complete snapshot before updating history; failure leaves
previous results untouched. Duplicate predictions reuse the existing sidecar.
Project save and autosave ensure missing snapshots are written before committing
JSON. Existing snapshots are checked without rewriting their arrays. Labels and
snapshot identities are verified when loading, with independent failures reported.

Method-based saved results still load structurally into candidates, without
rewriting their old files during loading. Their first subsequent save writes
candidate-addressed snapshots and metadata. The Mask chooser selects the sample's
active candidate independently of Method, which controls the next inference run.
Inference options are restored per sample/method without changing the displayed
mask. Mask names are editable, including literal names matching a method ID.
Keep protects a mask from automatic pruning. The Mask layer chooser
adds another saved mask as a read-only layer without changing the active mask.
Its layer-row remove button ends the comparison; compared masks are retained
while in use. Comparison
presentation is saved separately on that candidate, so changing its visibility,
color, opacity or blending does not alter its active-mask presentation. Switching
masks within a sample preserves the camera. Layer ordering is saved with the
active view. No duplicate comparison layer is drawn for the active candidate.

Each sample has at most one whole-image Reviewed for training revision, selected
independently of its active mask. Reviewing another candidate transfers the status
without changing list order or active selection. Lock and review are independent
markers in the chooser. Unaccepted edits cannot be reviewed; accepted corrections
start unreviewed while the previous reviewed snapshot remains available until the
user transfers review. Review changes update JSON without rewriting labels.

Project → Export training data… exports every reviewed sample, regardless of the
active tab, sample or mask. Each new training directory contains matching
uncompressed images/0001.tif and masks/0001.tif pairs plus manifest.json. Images
retain raw source values/dtype; instance masks retain IDs and exclude reversible
post-processing and working drafts. The manifest records sample/channel/source,
candidate/revision, model/run/parameter provenance and project units/resolution.
Publication is atomic: failed reads/writes leave no partial dataset, and existing
exports are never overwritten. The export does not dirty the project or retain
newly materialized source caches.

Pruning removes only live history entries. Sidecar files remain available to
older saved-project and recovery JSON, including after a run is discarded.
Automatic cleanup of unreferenced files is not performed.

`SegmentationEditSession` owns the mutable working copy for a sample's active
candidate. Editing/Post-processing tabs choose between that unprocessed mask and
the derived resized/filtered result. Selection uses thin white outlines with a
dark outer edge, kept at fixed screen width as zoom changes. Outline layers are
read-only, excluded from the layer controls and saved presentation, and never
become label data. Click selects; Ctrl+click toggles additional IDs. Inspection
and summaries read the working labels while Editing is active.

Basic editing uses filled freehand outlines and pixel-snapped round brushes.
Shift+outline adds to the selected instance; Ctrl+outline subtracts. Brush size
is an integer diameter: one pixel paints 1×1 and two pixels paint 2×2. Odd
sizes center on pixels and even sizes on pixel intersections. The transient Qt
brush overlay uses that same rasterizer and tracks the camera in canvas
coordinates. Light/dark shading and outline modifier cursors are viewer-only;
no decoration is added to mask data, Napari layers, saved state or exports. Pointer previews
are disposable; each released stroke commits one atomic command, including any
automatic disconnection split. Other instances are protected by default.
Eight-connected parts keep a surviving ID on the largest part when split;
other parts receive unused uint32 IDs.

The full-sized tool buttons expose viewer-scoped S/O/B/E/Delete shortcuts in
their tooltips. Pending Ask decisions are undoable with their stroke and saved
with drafts. Changing the selected segment resolves its pending questions before
selection moves, with the affected instance outlined. Clicked coordinates are
looked up again after splitting so selection follows the clicked part.
Accept changes publishes the corrected candidate; Reject changes discards the
whole working session. Navigating away from changed edits offers Accept, Reject
or Cancel. Accept also resolves any remaining disconnections; Cancel retains the
working session and current view. Unchanged editing creates no redundant history.


Merge combines selected instances into the largest selected instance's ID,
including intentionally disconnected selections. Split uses a dividing stroke
through one instance. It blocks crossings of the cut while retaining unrelated
diagonal connections, then assigns cut pixels to the nearest resulting part.
The mask area is preserved; the largest part keeps its ID. Explicit splitting
creates separate IDs regardless of the incidental-disconnection setting. A failed
cut makes no changes. Both operations are single undoable commands.

The Mask chooser's context menu extends normal name editing with Remove mask….
Removal requires confirmation and finishes or cancels any current edits first.
It removes only the selected candidate, retains corrected descendants and their
run provenance, and clears direct parent links to the removed candidate. The
newest retained mask becomes active when necessary. Comparison references to the
removed candidate are dropped; immutable sidecars stay available to older saved
project/autosave JSON. Reruns use the same Accept/Reject/Cancel boundary, and
accepted corrections remain protected if inference later fails.

Editing commands are atomic rectangular before/after patches, with undo/redo
scoped to the current session. Changed sessions are serialized as separate draft
snapshots with immutable revision paths; project save and autosave preserve them
without altering the source candidate. Undo stacks and selection are not saved.
Recovery resumes the draft in Editing. Entering, selecting, and leaving without
label changes creates neither a candidate nor dirty project state. Switching
mask/sample or returning to Post-processing finishes a changed session as a
protected corrected child; net-unchanged or merely renumbered labels do not add
history. Starting inference finishes editing first. Reviewed source snapshots
stay intact; corrected revisions start unreviewed. Drawing/brush tools follow in
the next editing stage.

`ClusteringWorker` retains the independent element-clustering path using the
imported numerical code and its own sample-level persistence. Both workers share
only progress/output capture and cooperative cancellation through `AnalysisTask`.
The controllers own thread lifetimes and publication of completed results.
`SegmentationViewer` accepts the result and referenced source map directly,
reusing the common Napari layer controls and fixed-layer pool. It displays the
postprocessed instance-label pixels and keeps computed labels read-only. It can
also show the selected input before any result exists. Optional reference layers
use the sample's element-map transformations and never become inference inputs.
Saved labels remain viewable when the source map is unavailable; mismatched map
shapes are not overlaid. Its click/hover inspection reads the displayed labels,
independently of tissue or cluster tables. Layer identities preserve per-sample,
per-method colors, opacity, gain, blending and ordering across result switches.
The controller preserves the camera when switching methods for one sample and
fits when changing samples. Editing controls occupy the upper-left pane; the
upper-right pane switches between an overview (counts, area statistics and cumulative
segment counts by area) and clicked-pixel details. Area statistics use pixels,
percent of the full image and squared project length units. An Overview
button restores the summary after inspection.
Expansion/shrinking precedes whole-instance area filtering, preserving surviving
label IDs. Expansion assigns background to the nearest segment without overlap;
shrinking erodes each instance independently, including at shared boundaries and
image edges. The signed distance and area cutoff are saved per sample/method.
The size-distribution plot uses the resized segments before area filtering, with
a vertical minimum-area cutoff marker; the summary uses the filtered result. Physical areas use the next
larger supported length unit squared to keep the displayed values compact.

Trained model metadata in `analysis.model_store` pins a release URL, expected
byte size and SHA-256 checksum independently of application versions. The
segmentation worker resolves missing weights before importing neural backends.
Transfers and first-use checksum checks run in that same cancellable worker,
with throttled progress forwarded to the existing GUI progress bar. Unique
partial files are replaced atomically only after validation; failed or cancelled
acquisition preserves any existing file and the previous segmentation result.
Unchanged verified files are reused offline. Expected acquisition errors are
shown as ordinary user-facing messages rather than internal-error traces.

`model_settings` reads the application-level model directory. Its default is
Exhale/models under the platform's per-user data location, independent of a
project or Git checkout. Changing the preference selects the location for later
runs; no models are downloaded on startup. The same location and acquisition
path are used by source and installed applications.

The Segmentation tab has one input-map selector. Its method options expose only
Cellpose's minimum area, flow threshold and cell-probability threshold. StarDist
currently has no exposed inference options; clipping remains internal to each
method. Mask export beside the mask chooser writes the original or edited uint32
instance-label array as TIFF, before reversible post-processing;
Save current view exports the rendered viewer separately.

Element correlations use the effective selected channels of one sample and
their untransformed source arrays. Between-sample similarities use only channel
keys selected and available in every included sample, so every fingerprint has
the same ordered features. Cluster-distance matrices use the centroids retained
in a sample's segmentation result and the project's XRF resolution to calculate
directed mean nearest-neighbour distances in physical units. These derived
matrices are disposable session state and are not part of the saved project.
Cluster-distance null simulations use independent centroid sets per element
within the union of existing segmentation cluster masks. A cancellable Qt worker
operates on private array snapshots. Its complete matrix is cached in pixels,
independently of the displayed minimum cluster count and XRF resolution.
Observed SD describes the spread of distances and can be shown alongside means
in project length units, pixels, or null-model normalized units. Null percentiles count simulated mean distances strictly below
the observation, with no multiple-testing correction. Percentile display uses
the full simulation precision (0.1 percentage points for 1,000 simulations),
a fixed 0–100% scale, and no secondary SD.
Element density views use regular bins spanning all paired finite values and
retain source values as plot coordinates. Bin counts are divided by their
value-space areas and interpolated in value space. The user can set the bin
count or instead show a bounded-size ordinary scatter plot.
Matrix plots share a renderer-independent specification between their
interactive view and a publication renderer for PDF, PNG, and SVG. Text
measurement, cell-size, label-extent, and colour-bar spacing rules are
calculated centrally. Export typography is shared by the project's matrix
plots, while dimensions and appearance belong to each matrix type. PDF and SVG
use vector cells and text; PNG uses the same physical layout at the selected
DPI.

Completed analysis is represented by one `SegmentationResult` per sample and
method in the project model. The stable method ID is saved in both the project
entry and sidecar. Large arrays and result tables are stored separately by
`exhale.analysis.segmentationio` in immutable candidate/revision HDF5 sidecars below the
project; the main project file stores the association, parameters, and layer
presentation. Layer presentation is keyed by fixed role or source element
reference so it remains valid across display-name changes and pooled Napari
layer reuse.

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
stores the window geometry, active tab, and all main-window splitter
layouts. Splitters restore only after their containing tab has usable geometry
and are saved only after they have been initialized. A saved layout containing
a completely collapsed pane is discarded in favor of the default proportions
so application state cannot make a panel effectively disappear on restart.

Static tooltip text is kept in `exhale.tooltips`, independently of Designer
XML and generated modules. The catalogue uses stable Qt object names and is
applied with strict lookup so UI renaming cannot silently drop help text.
Tooltips whose text changes with widget state remain with that behavior.

## Ownership rules

Mutable semantic state has one owner. Widgets display or edit it but must not
maintain independent authoritative copies. File-backed caches, composed
images, histograms, Napari layers, and formatted result tables are derived and
disposable.

Errors caused by user data should identify the affected source or operation
and remain recoverable where the rest of a project is usable. Programming
errors should fail clearly rather than being converted into plausible but
incorrect state.


## Distribution of segmentation libraries

Optional `stardist` and `cellpose` package extras supply the inference frameworks.
The base application imports neither backend eagerly. A
pinned DINOv3 source archive is installed through `requirements-cellpose.txt` for
source/pip installations and private installer-managed environments; public PyPI
metadata contains no direct URL requirement. The native installers install
selected libraries from their normal Python distributions. Only the large trained-model files use on-demand
acquisition. Normal application startup still avoids importing neural backends;
the explicit startup-check mode validates their imports without fetching weights.


## macOS runtime ownership

The Mac distribution uses a native AppKit setup/launcher and a private uv runtime,
separate from ordinary uv tool installations. The read-only app bundle contains
uv, the application wheel, a requirements file and the setup driver.
`packaging/macos/runtime.py` owns environment creation, startup validation, atomic
activation and removal under the current user's Application Support directory.
`Launcher.swift` owns backend selection and setup feedback. Installed inference
libraries and Python stay outside the bundle. Project/model storage is independent
of runtime removal. Builds use ad-hoc signing and are not Apple-notarized.


## Windows runtime ownership

Inno Setup owns the per-user installation, native launcher, shortcuts and private
runtime directory. `packaging/windows/Launcher.cs` creates a pending uv environment
from the bundled wheel and selected extras, validates startup, and activates it
only when Inno finishes copying files. It also launches the installed application
and provides setup rollback. Python 3.11, downloaded dependencies and installation
records belong to `{app}/runtime`; user projects and trained models do not.
Inno coordinates uninstallation, and native runtime locks protect active processes.

Segmentation editing help lives in a separate nonmodal, scrollable dialog. The
viewer resolves right-button brush inversion using the selected tool’s size. The
controller remembers separate drawing and erasing diameters for the shared input.
Each stroke is committed by the edit session as one undoable operation.

Rectangular segmentation selection is a transient Qt canvas overlay, intercepting
Shift drags before Napari navigation. The edit session resolves intersected pixel
IDs; the controller handles pending disconnections before changing selection.
It does not change labels, revisions, undo history or project dirty state.

Brush drawing allocates one new ID per stroke when selection is empty. Splitting
uses the stroke to identify its targets and commits all successful divisions in
one atomic command, preserving foreground pixels and untouched segments.
StarDist inference thresholds are method options; their initial values are read
from the bundled model metadata without importing a neural-network runtime.

Segmentation stroke completion is queued until Napari has released its drag
generator. Disconnection questions and edit-error dialogs may run nested Qt event
loops; opening them inside that generator would allow mouse events to re-enter it.
Cancellation or a changed editing session discards a pending completion.


## Assisted-boundary experiment

`analysis.boundaryfitting` provides non-mutating local fitting on original nuclei
intensities, with edge-based and region-intensity variants, a hard displacement
band and optional protected pixels. Curvature iteration state is local to a fit.
It has no neural-model or GUI dependencies. `analysis.boundarycalibration` creates
perturbed outlines and separates segments into training and validation groups;
parameter selection uses training scores only. The command-line experiment in
`tools/fit_boundary_parameters.py` reads accepted masks before post-processing
and writes separate reports and diagnostic crops. It does not save projects or
change segmentation history. The editor is not yet wired to these fitters.
