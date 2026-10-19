# Exhale code overview

This is the file-by-file guide to Exhale's hand-written Python. Generated Qt
modules are listed as a group because their source is the corresponding
Designer file, not the generated Python.

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
integrates with the PyInstaller splash screen.

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
segmentation results. `Sample`, `Channel`, `ChannelOverride`, and
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

### `exhale/project/projectmanager.py`

Owns project-directory selection and high-level new/open/save/save-as policy.
It coordinates model persistence, post-load UI refresh, and dirty-state
handling.

### `exhale/project/sourcemanager.py`

Owns source-file selection, import, removal, relocation, and source-handle cleanup. It
coordinates source-related model changes with the element, image, project-tab,
and dirty-state refreshes required after each operation.

### `exhale/project/projectstatemanager.py`

Tracks the canonical saved baseline, dirty state, delayed autosaves, recovery,
and prompts before replacing or closing a modified project.

### `exhale/analysis/segmentationio.py`

Stores and restores analyzed `XRFSample` objects in atomic HDF5 sidecars. Raw
and derived arrays remain datasets; pandas result tables use a JSON dataset
representation.

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

Provides the generated controls as a focused modal analysis-settings dialog;
`AnalysisController` reads and restores those controls.

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

Owns the Segmentation tab: its independent sample and channel selection,
parameter dialog, worker and thread lifetime, saved-result display,
incremental Napari updates, and result export. `MainWindow` supplies the
generated widgets and application-level services but owns no analysis state.

### `exhale/analysis/correlation_controller.py`

Owns the three independent Correlations subtabs, their sample and element
selection, disposable session caches, calculation requests, and result views.

### `exhale/analysis/correlations.py`

Computes element Pearson-correlation matrices with pairwise finite-value
filtering, between-sample similarities from aligned correlation fingerprints,
and value-positioned density grids for element scatter views.

### `exhale/analysis/analysisworker.py`

Defines the background `AnalysisWorker`. It captures Python and native stderr,
emits progress, constructs an `XRFSample`, runs processing and combination,
and returns either the result or a traceback through Qt signals.

### `exhale/xrf_refcopy/xrf_sample_class.py`

Defines `XRFSample`, the coordinator for nuclei, tissue, and element channels.
It validates readiness, runs channel processing, and combines per-region data
into result tables.

### `exhale/xrf_refcopy/xrf_element_channel.py`

Defines `ElementChannel`, which log-transforms an element map, selects an exact
one-dimensional intensity partition, labels small connected regions, and
records their properties.

### `exhale/xrf_refcopy/xrf_other_channel.py`

Defines `NucleiChannel` and `TissueChannel`. They segment nuclei, construct
expanded membrane regions, and derive the tissue mask used by sample-level
analysis.

### `exhale/xrf_refcopy/xrf_utils.py`

Contains the numerical analysis functions: StarDist model loading, nuclei and
membrane operations, connected-region filtering, exact weighted intensity
partitioning, and compatibility wrappers used by the channel classes.

## Visualization and reusable widgets

### `exhale/analysis/naparihelper.py`

Encapsulates the embedded Napari viewer, its Qt widget, map and analysis
layers, layer-selection synchronization, and in-place element-map updates that
preserve layer presentation state.

### `exhale/analysis/layerwidgets.py`

Implements the layer list shown beside Napari. Rows expose visibility, colour,
opacity, blending, and reorder/remove operations while reflecting the actual
viewer layers.

### `exhale/analysis/correlationwidgets.py`

Provides independent reusable correlation-matrix views and the pyqtgraph
heat-map/scatter plotting widgets used by the Correlations tab.

### `exhale/imaging/listwidgets.py`

Contains the element and image list widgets, colour button, and compact image
channel/header control rows used by the main window.

### `exhale/widgets.py`

Contains small general Qt helpers: square icon buttons and deferred splitter
initialization for pages which are hidden during initial layout.

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

### `exhale/data/constants.py`

Holds shared fixed values, currently physical display-unit scales.

### `exhale/runtimeinfo.py`

Collects Python, Qt, binding, and dependency versions and formats the About
dialog's runtime-information table.

## Generated UI modules and resources

`exhale/analysis/analysis_settings_dialog_ui.py`,
`exhale/imaging/image_settings_dialog_ui.py`, `exhale/main_window_ui.py`, and
`exhale/settings_dialog_ui.py` are generated from the same base names under
`exhale/resources/ui/`. Edit the `.ui` files and regenerate; never edit or
document generated modules directly.

`exhale/resources/icons/` contains packaged SVG and raster artwork.
`exhale/resources/models/` contains the bundled StarDist model data.
`artwork/generate/` contains the indexed mask, appearance reference, deterministic
guide and alpha-mask utilities, and ImageGen procedure for XRF artwork. `artwork/logos/`
contains selected full-size logo sources and retained alternatives;
`artwork/splash/` contains editable splash-screen sources; and
`artwork/unused-icons/` retains interface icons which are not packaged or used
at runtime.

## Packaging and tests

`packaging/` contains the PyInstaller specification and hooks, Windows Inno
Setup definition, Conda recipe, generated platform icon containers, and the
utility which rebuilds those containers from a selected artwork source.
`.github/workflows/build.yml` builds Windows, Linux, and macOS frozen
applications and publishes tagged packages.

`tests/` contains the pytest/unittest regression suite. Test modules generally
follow their corresponding application module or workflow; GUI tests use the
off-screen Qt platform where possible.
