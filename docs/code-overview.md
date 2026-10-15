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

Application entry point. It optionally recompiles changed Designer files,
creates `QApplication` and `MainWindow`, initializes appearance and icons,
handles initial files or projects, and reports top-level failures. It also
integrates with the PyInstaller splash screen.

## Project model, input, and persistence

### `exhale/data/__init__.py`

Defines the data-model package boundary. Modules in this package must remain
independent of Qt widgets.

### `exhale/data/projectdata.py`

Defines the authoritative project model. `ProjectData` owns assets, samples,
project channel choices, shared defaults, and segmentation results. `Sample`,
`Channel`, `ChannelOverride`, and `ResolvedChannel` express local versus
inherited channel state; the remaining data classes describe assets and
analysis metadata.

### `exhale/data/channeldata.py`

Provides uniform access to map data. `ChannelData` defines the cache and
availability contract, `ArrayChannelData` wraps in-memory arrays, and
`SourceChannelData` reads lazily from an open source.

### `exhale/data/source_refs.py`

Defines `ElementRef`, `ElementCandidate`, `LoadedSource`, and the HDF5/TIFF
reader. It validates supported source layouts, owns file handles, enumerates
maps, and translates TIFF pages or components into stable item identifiers.

### `exhale/data/tiffimport.py`

Infers conservative sample and channel-name suggestions from TIFF filenames.
`TiffImportProposal` keeps those suggestions explicit and editable.

### `exhale/projectio.py`

Serializes and restores project JSON. It owns path relocation, model and image
settings encoding, project-header validation, tolerant object loading, and
atomic writes.

### `exhale/projectmanager.py`

Owns project-directory selection and high-level new/open/save/save-as policy.
It coordinates `projectio`, the main window, and dirty-state handling.

### `exhale/projectstatemanager.py`

Tracks the canonical saved baseline, dirty state, delayed autosaves, recovery,
and prompts before replacing or closing a modified project.

### `exhale/segmentationio.py`

Stores and restores analyzed `XRFSample` objects in atomic HDF5 sidecars. Raw
and derived arrays remain datasets; pandas result tables use a JSON dataset
representation.

## Settings and composition

### `exhale/data/elementsettings.py`

Defines channel normalization choices, shared `ElementSettingsDefaults`, and
`ElementSettings`, which combines a channel reference and data accessor with
its display name, gamma, normalizer, and transfer range.

### `exhale/data/imagesettings.py`

Defines image layouts, colour schemes, scale-bar positions, and
`ImageSettings`. It records selected channels, explicit image-local overrides,
resolution, labels, borders, and export settings.

### `exhale/imagecomposer.py`

Builds exact RGBA output from `ImageSettings`. `ImageComposer` handles merged
and strip layouts, colours, labels, scale bars, resizing, and optional file
output; `ComposedImageMapping` maps canvas pixels back to source coordinates.

### `exhale/imagecanvas.py`

Provides the pyqtgraph image canvas. `ImageViewBox` keeps square pixels and
constrains panning, while `ImageCanvas` displays image arrays and exposes
fit/reset and coordinate behavior.

### `exhale/histogramwidget.py`

Displays histogram bins and two ordered draggable normalization limits using
pyqtgraph.

## Main window and focused controllers

### `exhale/main_window.py`

Defines `MainWindow`, the application shell and integration point. It creates
feature helpers, connects generated controls, synchronizes selected channels
and images, launches analysis, and routes project and error operations to
their owners.

### `exhale/project_tab.py`

Coordinates the Project data tab. `ProjectTab` populates the sample/file tree,
channel and map lists, resolution controls, add/remove actions, channel
inheritance, and stable tree sizing without owning the underlying model.

### `exhale/analysis_settings_dialog.py`

Provides the generated controls as a focused modal analysis-settings dialog;
the main window transfers values to and from those controls.

### `exhale/image_settings_dialog.py`

Provides the generated controls as a focused modal image-settings dialog; the
main window transfers defaults or one image's settings to and from it.

### `exhale/settings_dialog.py`

Edits persistent application preferences in `QSettings`, currently appearance
and project autosave behavior.

## Analysis

### `exhale/analysisworker.py`

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

### `exhale/naparihelper.py`

Encapsulates the embedded Napari viewer, its Qt widget, map and analysis
layers, and layer-selection synchronization.

### `exhale/layerwidgets.py`

Implements the layer list shown beside Napari. Rows expose visibility, colour,
opacity, blending, and reorder/remove operations while reflecting the actual
viewer layers.

### `exhale/listwidgets.py`

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

`exhale/analysis_settings_dialog_ui.py`, `image_settings_dialog_ui.py`,
`main_window_ui.py`, and `settings_dialog_ui.py` are generated from the same
base names under `exhale/resources/ui/`. Edit the `.ui` files and regenerate;
never edit or document generated modules directly.

`exhale/resources/icons/` contains packaged SVG and raster artwork.
`exhale/resources/models/` contains the bundled StarDist model data.

## Packaging and tests

`packaging/` contains the PyInstaller specification and hooks, Windows Inno
Setup definition, Conda recipe, platform icon sources, and icon-generation
utilities. `.github/workflows/build.yml` builds release artifacts and publishes
tagged packages.

`tests/` contains the pytest/unittest regression suite. Test modules generally
follow their corresponding application module or workflow; GUI tests use the
off-screen Qt platform where possible.
