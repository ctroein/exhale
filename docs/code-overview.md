# Exhale code overview

This is the file-by-file guide to Exhale's maintained Python source. Generated Qt
modules are listed as a group because their source is the corresponding
Designer file, not the generated Python.

## Dependency trials

### `tools/try_application_update.py`

Builds a source snapshot with two temporary versions and serves a localhost
package index and release-check endpoint. It installs and launches the older
version in an isolated uv tool environment, then offers the newer one for manual
testing of notification, quit cancellation, upgrade and restart. Application
settings are isolated; normal dependency downloads use the shared uv cache.

### `tools/try_dependency_updates.py`

Creates a fresh Linux environment with selectable backend extras and current stable dependencies, preserves
explicit compatibility exceptions, records installed versions, runs automated
checks, and launches the checkout for manual testing. Existing trials can be
reused while investigating and fixing failures.

## Boundary-fitting experiment

### `tools/fit_boundary_parameters.py`

Reads saved project masks and original nuclei intensities for offline parameter
comparison. Selects samples/masks, writes JSON/CSV results and diagnostic PNG/NPZ
crops, and closes source handles without saving the project. Usage and experiment
assumptions are in [`boundary-fitting.md`](boundary-fitting.md).

### `exhale/analysis/boundaryfitting.py`

Fits closed outlines with directional normal searches, cyclic displacement
coordination and bending regularization. Preserves topology, displacement bounds
and protected pixels. Retains the earlier edge/region pixel-mask evolution for
offline comparisons. Does not mutate inputs or import a neural runtime.

### `exhale/analysis/boundarycalibration.py`

Builds deterministic outline perturbations, separates complete segments into
training and validation groups, scores overlap/boundary distance, and chooses
method parameters on the training group before withheld evaluation.

## Launch and package files

### `run_exhale.py`

Minimal development launcher. It imports and calls `exhale.__main__.main()`.

### `exhale/__init__.py`

Defines application identity, resource paths, and the version reported by the
installed package or source checkout.

### `exhale/__main__.py`

Application entry point. It optionally recompiles changed Designer files, can
recompile every generated UI module without launching the application,
creates `QApplication` and `MainWindow`, initializes appearance and icons,
handles initial files or projects, and reports top-level failures. It also
updates the Qt splash screen during startup.

## Project model, input, and persistence

### `exhale/project/__init__.py`

Defines the package boundary for saved-project persistence, lifecycle policy,
and project controls.

### `exhale/data/__init__.py`

Defines the data-model package boundary. Modules in this package must remain
independent of Qt widgets.

### `exhale/data/projectdata.py`

Defines the authoritative project model. `ProjectData` owns assets, samples,
composed-image settings, project channel choices, shared defaults, and
segmentation results and independent element-clustering results, each with saved
viewer-layer presentation. Segmentation results retain reversible post-processing
and reference-map selections, with preview state before the first successful run.
The next-run segmentation method is a project preference; editing-tool preferences
are kept in application settings by `AnalysisController`.
Empty manual segmentation candidates can be created from a sample map without a
neural method, then edited and persisted through the ordinary mask history.
Working masks advance revisions without creating chooser entries for each edit;
the first correction of a prediction retains the original as a separate mask.
`Sample`, `Channel`, `ChannelOverride`, and
`ResolvedChannel` express local versus inherited channel state; the remaining
data classes describe assets and analysis metadata.

### `exhale/data/channeldata.py`

Provides uniform access to map data. `ChannelData` defines the cache and
availability contract, `ArrayChannelData` wraps in-memory arrays, and
`SourceChannelData` reads lazily from an open source.

### `exhale/data/source_refs.py`

Defines `ElementRef`, `ElementCandidate`, `LoadedSource`, and the HDF5/TIFF
reader. It validates supported source layouts, owns file handles, enumerates
maps, and translates TIFF pages or components into stable item identifiers.
OME-TIFF channel names become the suggested channel names and keys.

### `exhale/data/tiffimport.py`

Infers conservative sample and channel-name suggestions from TIFF filenames.
`TiffImportProposal` keeps those suggestions explicit and editable.

### `exhale/project/projectio.py`

Serializes and restores `ProjectData` without accessing windows or widgets. It
owns path relocation, model and image settings encoding, project-header
validation, tolerant object loading, and atomic writes.
It checks live state and saved project/autosave manifests before asking the
segmentation storage layer to remove obsolete label snapshots.

### `exhale/project/projectmanager.py`

Owns project-directory selection and high-level new/open/save policy.
It coordinates model persistence, post-load UI refresh, dirty-state handling,
and the shared default location for exported project output. Owns the project-wide
training-export action and destination selection.

### `exhale/project/sourcemanager.py`

Owns source-file selection, import, removal, relocation, and source-handle cleanup. It
coordinates source-related model changes with the element, image, project-tab,
and dirty-state refreshes required after each operation.

### `exhale/project/projectstatemanager.py`

Tracks the canonical saved baseline, dirty state, delayed autosaves, recovery,
and prompts before replacing or closing a modified project.

### `exhale/analysis/trainingio.py`

Exports the project's reviewed raw source maps and accepted instance masks as
uncompressed TIFF pairs with a JSON provenance manifest. Review is independent of
active selections. Stages complete datasets before publication, cleans up failed
exports, preserves source values and label IDs, and releases newly read caches.

### `exhale/data/segmentationbatch.py`

Defines immutable sample/channel jobs and lightweight nuclei-channel suggestions
from existing assignments or P/P_* keys. Offers effective available channels
without materializing map arrays.

### `exhale/analysis/segmentation_batch_dialog.py`

Reviews explicit batch scope and per-sample nuclei inputs in stable
sample rows. Designer source is `segmentation_batch_dialog.ui`; generated output
is `analysis/segmentation_batch_dialog_ui.py`.

### `exhale/analysis/segmentationbatch.py`

Owns the sequential batch worker and transient queue lifecycle. Loads one raw map
at a time, reuses model acquisition/inference, publishes completed candidates on
the GUI thread without replacing an active mask or working edits, aggregates
failures, and invalidates queued callbacks when a project is cleared or closed.

### `exhale/analysis/segmentationio.py`

Stores immutable segmentation-only snapshots atomically in HDF5, addressed by
sample/candidate/revision IDs. Saves before history publication, verifies snapshot
identity and content, and reuses existing files without rewriting arrays.
Reads structurally usable method-based and nested label datasets directly.
Separate `save_xrf_sample` / `load_xrf_sample` functions retain the element-clustering
sidecars, indexed by sample, with arrays and JSON-encoded pandas tables.

### `exhale/fileio.py`

Reserves sibling staging files and directories with normal creation permissions,
so published output inherits the destination parent's default ACL and process
umask. Directory staging cleans up unpublished data on failure; file writers
retain responsibility for atomic replacement and cleanup.

## Settings and composition

### `exhale/imaging/__init__.py`

Defines the package boundary for image composition, display, and
image-specific Qt controls.

### `exhale/data/elementsettings.py`

Defines channel normalization choices, shared `ElementSettingsDefaults`, and
`ElementSettings`, which combines a channel reference and data accessor with
its display name, gamma, normalizer, and transfer range.

### `exhale/data/imagesettings.py`

Defines image layouts, colour schemes, scale-bar positions, and
`ImageSettings`. It records selected channels, explicit image-local overrides,
resolution, labels, borders, and export settings.

### `exhale/imaging/imagecomposer.py`

Builds exact RGBA output from `ImageSettings`. `ImageComposer` handles merged
and strip layouts, colours, labels, scale bars, resizing, and optional file
output; `ComposedImageMapping` maps canvas pixels back to source coordinates.

### `exhale/imaging/imagecanvas.py`

Provides the pyqtgraph image canvas. `ImageViewBox` keeps square pixels and
constrains panning, while `ImageCanvas` displays image arrays and exposes
fit/reset and coordinate behavior.

### `exhale/imaging/histogramwidget.py`

Displays histogram bins and two ordered draggable normalization limits using
pyqtgraph.

## Main window and focused controllers

### `exhale/main_window.py`

Defines `MainWindow`, the application shell and integration point. It creates
feature controllers and managers, connects application-wide events, presents
global dialogs, persists window and splitter state, and coordinates global
project refresh and shutdown.

### `exhale/project/project_tab.py`

Coordinates the Project data tab. `ProjectTab` populates the sample/file tree,
channel and map lists, resolution controls, add/remove actions, channel
inheritance, and stable tree sizing without owning the underlying model.

### `exhale/imaging/element_controller.py`

Owns Element maps selection and editing: the selected sample and element,
effective channel-state presentation, normalization and histogram controls,
element naming, and single-map display. It creates missing `ElementSettings`
objects while leaving them authoritatively owned by `ProjectData`.

### `exhale/imaging/image_controller.py`

Owns composed-image selection and editing, channel slots and local overrides,
presentation defaults, the image-settings dialog, `ImageComposer` and canvas
mapping, image export, and image-related UI state. The saved image collection
remains owned by `ProjectData`.

### `exhale/analysis/analysis_settings_dialog.py`

Provides the generated controls used by the independent element-clustering
options dialog.

### `exhale/imaging/image_settings_dialog.py`

Provides the generated controls as a focused modal image-settings dialog; the
`ImageController` transfers defaults or one image's settings to and from it.

### `exhale/settings_dialog.py`

Edits persistent application preferences in `QSettings`, currently appearance
and project autosave behavior.

## Analysis

### `exhale/analysis/__init__.py`

Defines the package boundary for analysis execution, persistence, and result
visualization.

### `exhale/analysis/controller.py`

Owns the Segmentation tab: independent sample and active-mask selection, the next
run's method/input selection, editable mask names, Keep and comparison controls, segmentation-only options, worker lifetime, saved-mask display,
Napari view, reversible area filtering, input preview, reference-map selection,
overview/cumulative area distribution, clicked-segment details and result export.
Also owns Editing/Post-processing mode, editing-tool controls, selection, undo/redo,
early disconnection questions, merge/split controls, explicit Accept/Reject,
cancellable navigation, confirmed mask removal and whole-image review.
Owns optional edge-based outline fitting and its compact tool controls;
fitted outlines apply on release as one undoable edit.
Element selection and clustering options belong
to the independent Element clusters controller. `MainWindow` supplies the
generated widgets and application-level services but owns no analysis state.

### `exhale/analysis/clustering_controller.py`

Owns the Element clusters tab before Segmentation: method/options selection,
single and batch execution, incremental publication and lightweight display of
one element map with its clusters. Element switches reuse two pooled overlays
and preserve the camera and shared map/cluster presentation. Each overlay has a
color control; the full layer list is not replicated.

### `exhale/data/clustering.py`

Defines the default method ID and immutable sample jobs containing all enabled
elements, captured in stable order with separate keys, display names and refs.

### `exhale/analysis/clusteringmethods.py`

Registers clustering methods with numerical execution and options-dialog
adapters. Intensity partitioning is the initial method. Dependencies and model
choices remain independent of segmentation.

### `exhale/analysis/clusteringbatch.py`

Runs sample jobs sequentially in a background thread, reads original maps,
saves results before publishing each completed sample, checks cancellation and
continues after independent sample failures.

Reports determinate progress across element processing and sample saves, including
failed samples, while cancellation retains the last completed work position.

### `exhale/analysis/clustering_batch_dialog.py`

Chooses sample scope, reports enabled-element counts and unavailable inputs,
and provides explicit selection of samples without output from this method. Designer source is
`clustering_batch_dialog.ui`; generated output has the matching `_ui.py` suffix.

### `exhale/analysis/batchselection.py`

Shares All/None/Unprocessed check-state actions between both batch dialogs.
The checked rows define the scope directly; no separate skip policy filters jobs.

### `exhale/data/segmentation.py`

Defines backend-independent parameter snapshots and validated segmentation output.
Output owns a copy of integer instance labels and records trained-model identity
and version, with no tissue, membrane or clustering state. Also defines Euclidean
boundary expansion/shrinking, minimum-area post-processing and sparse-label area
operations. The result model caches resizing separately from area filtering, so
cutoff edits reuse the resized labels. Original output remains separate.

### `exhale/data/segmentationhistory.py`

Defines sample-level `SegmentationHistory`, mask candidates and inference-run
provenance. Candidates own label and settings snapshots, stable candidate/revision
identities, names, parent links, Keep and annotation/review state. History merges
identical region partitions independently of numeric label IDs, retains run
provenance across methods, and keeps five recent unprotected predictions plus
protected/active masks and ancestors needed by retained revisions. Enforces one
reviewed mask per sample independently of the active candidate. Selection does
not reorder candidates. Existing result objects can be imported independently
with malformed entries reported and skipped. Deliberate removal retains descendant
masks/provenance and cleans active, parent and comparison references.

`ProjectData.segmentation_histories` is authoritative. JSON persists candidates,
active selection, provenance and retention order. Compared masks are protected
while in use, with their comparison presentation saved separately. History can
be restored before pruning, preserving out-of-order parent links and reporting
missing independent records.

### `exhale/data/segmentationref.py`

Defines immutable, JSON-serializable downstream mask references: sample, candidate,
revision and post-processing settings. References compare against an explicitly
chosen input and resolve the recorded processed labels while that exact mask is
retained. Missing masks never fall back to another candidate. `ProjectData` exposes
capture, currency-check and exact-resolution methods for future consumers.

### `exhale/data/segmentationediting.py`

Owns an undoable working copy of an immutable mask candidate. Commands retain
changed rectangular before/after patches with revision identities; selected IDs
and undo history remain session-only. Changed sessions produce cached immutable
draft snapshots for normal saving/recovery. Finishing creates a corrected child
candidate only when region geometry differs from its source. Unchanged editing
does not create candidates or serialized drafts.
Rasterizes additive/subtractive outlines with non-zero winding fill, preserving
opposite-direction holes while keeping same-direction overlaps filled, and pixel-snapped integer-diameter brush
strokes, protects other instances, allocates
IDs and handles incidental disconnection atomically. Drafts also retain pending
disconnection questions. Merge and dividing-stroke split are atomic commands;
split preserves foreground pixels and refuses ineffective cuts.

### `exhale/analysis/segmentation_backends.py`

Owns non-mutating percentile preprocessing, safe lazy neural-library initialization,
direct StarDist/Cellpose inference and MONAI dispatch, model caching and
model-content provenance.
Validates the labels against the input shape without downstream filtering or regions.

### `exhale/analysis/segmentation_monai.py`

Loads the bundled residual U-Net lazily, normalizes clipped raw maps and blends
original-resolution tile logits before a single watershed conversion. Reuses
models by file revision/device, checks cancellation at tile boundaries, and
converts interior/boundary probabilities to instance labels with fallback seeds.

### `exhale/analysis/segmentation_options_dialog.py`

Edits method-specific StarDist, Cellpose and MONAI U-Net inference settings, retaining
separate method controls and internal preprocessing parameters. StarDist defaults
come from bundled model metadata without initializing a backend.

### `exhale/analysis/segmentation_viewer.py`

Presents a `SegmentationResult` directly using pooled source-map and read-only
instance-label layers, explicitly added reference maps and read-only comparison
masks, plus screen-width selection outlines and native outline/brush gestures with
cancellable previews. Selection decoration is excluded
from layer controls and label export. Comparison layers have stable candidate identities and are removed when
no longer requested, avoiding retention of discarded arrays. Reuses common Napari
presentation controls while keeping hover/click inspection independent of the
clustering model. Displays processed labels, supports input-only preview, and
refreshes transformed reference maps without changing their presentation.
Missing source data do not hide saved segmentation output.

### `exhale/analysis/segmentationcursor.py`

Draws the transient brush footprint above the Qt/OpenGL canvas using the editing
rasterizer, custom plus/minus cursors for modifier outlines, and marching-ants
rectangles for Shift-drag area selection, plus open outline strokes without a
filled closing fan. It follows
camera transforms, brush size and pointer/modifier events without adding viewer
layers or changing mask data, presentation, exports or project state.

### `exhale/analysis/model_store.py`

Defines pinned trained-model release metadata and cancellable HTTP/local transfer.
Verifies file size and SHA-256, caches verification for unchanged files, and
atomically installs complete weights. It imports neither Qt nor neural libraries.

### `exhale/model_settings.py`

Resolves the application model-directory preference and platform-appropriate
per-user default, independently of projects and launcher paths.

### `tools/prepare_model_release.py`

Checks the supplied trained model against the pinned catalog and prepares a
release asset, checksum file, JSON metadata and DINOv3 license. It never uploads or creates a
GitHub release.

### `exhale/analysis/segmentationmethods.py`

Defines the lightweight segmentation-method registry. Stable method IDs,
dependency checks, capabilities, display names, and worker construction live
here so populating method selectors does not import numerical backends.
The startup-check helper imports installed backends and rejects incomplete
installations while allowing either backend to be absent.

### `exhale/analysis/correlation_controller.py`

Owns the independent Relationships subtabs, their sample and element selection,
disposable session caches, calculation requests, and result views. Cluster-distance
null statistics run in a cancellable worker using private array snapshots; late
results cannot replace a different selection or a newly loaded project.

### `exhale/analysis/correlations.py`

Computes element Pearson-correlation matrices with pairwise finite-value
filtering, between-sample similarities from aligned correlation fingerprints,
and value-positioned density grids for element scatter views.

### `exhale/analysis/cluster_distances.py`

Computes directed mean nearest-centroid distances between the segmented
clusters of each pair of elements in physical project units. Simulates complete
directed matrices within the unexpanded union of segmentation cluster masks,
returning null means and unbiased variances in pixels for resolution-independent
caching and normalization, and empirical percentiles from strictly lower
simulated means.

### `exhale/analysis/analysisworker.py`

Defines segmentation-only `AnalysisWorker` and independent `ClusteringWorker`,
sharing only `AnalysisTask` execution, output capture, progress and cancellation.
Segmentation returns a pure `SegmentationOutput`; only clustering imports and
constructs the legacy `XRFSample`. Completion or failure is returned through Qt signals.

### `exhale/xrf_refcopy/xrf_sample_class.py`

Defines the legacy `XRFSample` used by element clustering and its sidecars.
It clusters element channels and retains region-table/export data from existing
results. Old combined `process()` and segmentation entry points are removed;
segmentation uses the independent backend and result model.

### `exhale/xrf_refcopy/xrf_element_channel.py`

Defines `ElementChannel`, which log-transforms an element map, selects an exact
one-dimensional intensity partition, labels small connected regions, and
records their properties.

### `exhale/xrf_refcopy/xrf_other_channel.py`

Retains `NucleiChannel` as a data container for legacy region results and
`TissueChannel` for downstream tissue-mask processing. Neither calls a neural
segmentation method.

### `exhale/xrf_refcopy/xrf_utils.py`

Contains region operations, membrane expansion, intensity filtering and exact
weighted intensity partitioning for downstream analysis. Log scaling ignores
non-finite source pixels; element clustering leaves those pixels unlabeled. StarDist loading and
inference helpers are removed; clustering imports no neural backend.

## Visualization and reusable widgets

### `exhale/analysis/naparihelper.py`

Encapsulates the embedded Napari viewer, its Qt widget, map and analysis
layers, layer-selection synchronization, exclusive Solo viewing with preserved checkbox
choices, and in-place element-map updates that
preserve layer presentation state. Fits initial content to actual canvas sizes
while startup layouts settle, stopping on user interaction or leaving the view.
Owns the shared maximally separated hue picker used by image Auto colors and
new element layers and monochrome comparison masks. It considers enabled image
colors and monochrome label colors, ignoring categorical palettes.

### `exhale/analysis/layerwidgets.py`

Implements the layer list shown beside Napari. Rows expose visibility, colour,
opacity, Normal/Add/Solo cycling, and reorder/remove operations while reflecting the actual
viewer layers.
Clustering overlays can be added to the Segmentation viewer from saved sample/method
results; their identities and presentation are retained with viewer layer settings.
`LayerColorEditor` owns the reusable swatch and color actions shared by layer
rows and the lightweight clustering overlay controls.
For label layers, the main color-button click cycles categorical, monochrome mask
and monochrome scale. The dropdown selects one of five categorical palettes or
uses the shared image-color menu for either monochrome mode. Mode changes retain
the selected palette and base color. Each categorical palette uses its own fixed
seed to shuffle the original colors, retaining that assignment across refreshes.
Palette 1 is unchanged; palettes 2–3 progressively reduce saturation and raise
brightness. Palette 4 raises only saturation, and palette 5 only brightness,
each halfway from the original HSV component to its maximum.

### `exhale/analysis/correlationwidgets.py`

Provides independent reusable correlation-matrix views and the pyqtgraph
heat-map/scatter plotting widgets used by the Correlations tab.

### `exhale/analysis/matrixplots.py`

Defines renderer-independent matrix data, value formatting, text measurements,
and spacing rules shared by interactive and export renderers.

### `exhale/data/matrixpalettes.py`

Defines the shared matrix palette catalog and derives the valid palette keys
used by project settings.

### `exhale/analysis/matrix_export_dialog.py`

Edits project-wide matrix typography and the physical dimensions and appearance
settings belonging to one publication matrix plot.

### `exhale/analysis/matrixpdf.py`

Lays out and renders publication correlation matrices as vector PDF and SVG or
as PNG at a selected DPI, with physical dimensions and project-owned
typography.

### `exhale/data/plotsettings.py`

Defines project-owned settings for matrix palettes, displayed values,
dimensions, resolution, cell borders, and colour-bar placement, keyed so
future matrix plot types can reuse them.

### `exhale/imaging/listwidgets.py`

Contains the element and image list widgets, colour button, and compact image
channel/header control rows used by the main window.

### `exhale/widgets.py`

Contains small general Qt helpers: square icon buttons and deferred splitter
initialization for pages which are hidden during initial layout.

### `exhale/tooltips.py`

Contains the authoritative catalogue of static interface tooltips and strict
helpers which apply them to generated or programmatically constructed widgets.
State-dependent tooltips remain beside the behavior which changes them.

### `exhale/appearance.py`

Owns light, dark, and system palette selection. `AppearanceManager` applies
the persistent choice and emits palette changes; `SplitterGripStyle` provides
the shared Fusion splitter grip.

### `exhale/icons.py`

Defines the typed icon catalogue and palette-aware SVG rendering. Icons and
pixmaps are cached until the palette changes.

### `exhale/overridecursor.py`

Provides `OverrideCursor`, a context manager around Qt's application-wide
override cursor stack.

### `exhale/exceptiondialog.py`

Presents handled and unhandled error details. `ExceptionDetailsDialog` is the
modal widget; `ExceptionDialog` installs the top-level exception hook.

## Application information

### `exhale/updates.py`

Identifies native-managed runtimes and writable Linux uv tool installations,
filters PyPI releases for the current Python, and stages update requests. Native
requests go to the parent launcher with an instance token after GUI shutdown;
Linux uv tools use a detached standard-library helper. Process
lifetime and installation locks protect the running environment. The helper
uses uv's recorded requirements, verifies the resulting version and startup,
records a log and result, and reopens Exhale.

### `exhale/update_controller.py`

Owns the cross-platform background release-check worker, daily scheduling, notifications,
explicit update confirmation, cancelled-close handling and reporting the
previous helper result. Settings exposes the preference and manual check.

`exhale.__main__` also owns the Linux per-user desktop registration commands.
The packaged desktop-entry template is filled with the current installation's
launcher and installed together with the application icon under the user's XDG
data directory. Registration remains explicit so pip and uv installations use
the same mechanism.

### `exhale/data/constants.py`

Holds shared fixed values, currently physical display-unit scales.

### `exhale/runtimeinfo.py`

Collects Python, Qt, binding, and dependency versions and formats the About
dialog's runtime-information table.

## Generated UI modules and resources

`exhale/analysis/analysis_settings_dialog_ui.py`,
`exhale/analysis/segmentation_options_dialog_ui.py`,
`exhale/analysis/segmentation_batch_dialog_ui.py`,
`exhale/analysis/clustering_batch_dialog_ui.py`,
`exhale/imaging/image_settings_dialog_ui.py`, `exhale/main_window_ui.py`, and
`exhale/settings_dialog_ui.py` are generated from the same base names under
`exhale/resources/ui/`. Edit the `.ui` files and regenerate; never edit or
document generated modules directly.

`exhale/resources/icons/` contains packaged SVG and raster artwork.
`exhale/resources/models/` contains the bundled StarDist model data.
`artwork/generate/` contains the indexed splash mask, deterministic mask-point,
guide and icon-source generators, appearance reference, splash installer, and
ImageGen procedure for XRF artwork; and
`artwork/unused-icons/` retains interface icons which are not packaged or used
at runtime.

## Packaging and tests

`packaging/` contains the native macOS setup app, Windows Inno Setup definition,
generated platform icon containers, and the utility which rebuilds
those containers from a selected artwork source. `requirements-cellpose.txt`
pins DINOv3 for source/pip installations and the native installers.

`.github/workflows/build.yml` builds Windows installers and macOS DMGs with private
uv environments and publishes the Python package. Windows startup checks can also
be dispatched separately for ordinary pip installations.

`tests/` contains the pytest/unittest regression suite. Test modules generally
follow their corresponding application module or workflow; GUI tests use the
off-screen Qt platform where possible.


## Native macOS distribution

### `packaging/macos/build.py`

Builds the Swift launcher, bundles a local EXHALE wheel and checksum-verified uv,
and produces an ad-hoc-signed app and DMG for the build machine's architecture.

### `packaging/macos/Launcher.swift`

AppKit setup interface and launcher. Offers supported backend choices, streams
setup output, starts the private Python driver, and exposes runtime removal.
Its `--setup-check` entry point exercises the setup driver on GitHub runners.
Headless `--update-runtime` and `--startup-check` entry points exercise updates
and subsequent launches through that same driver.

### `packaging/macos/runtime.py`

Owns EXHALE's private Python environments and installation record. Installs selected
extras from the bundled wheel, checks startup before activation, preserves a
previous environment on failure, and locks setup against a running application.
Consumes application update requests after process exit, installs the requested
PyPI version with the existing backends, records the result, and reopens Exhale.


## Native Windows distribution

### `packaging/test_runtime_updates.py`

Builds temporary local test wheels and exercises the installed native launcher's
update operation, selected backend preservation, startup of both versions and
recovery after a deliberately rejected version. It retains diagnostic logs for
Windows and both Mac architectures in the build workflow.

### `packaging/win_build.py`

Builds the native launcher with Windows' C# compiler, verifies and stages uv,
bundles a local application wheel and DINOv3 requirements, runs native self-tests,
and invokes Inno Setup.

### `packaging/windows/Launcher.cs`

Native launcher and private runtime manager. Prepares selected backends with uv,
checks startup, activates pending environments, rolls back unfinished setup and
forwards application arguments. Supplies runtime locking and installation logs.
Passes native runtime identity to the application and consumes update requests
after it exits. Validates new runtimes before activation and reopens the working
application after either success or rejected preparation.

### `packaging/windows/test-installer.ps1`

Windows runner integration checks for the actual Inno installer: backend choices,
upgrades, installed dependency presence, startup, and uninstallation.

### `exhale/analysis/segmentation_help_dialog.py`

Resizable, scrollable editing help with tool operations and keyboard shortcuts.
