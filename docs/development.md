# Exhale development conventions

This document describes the conventions and invariants for work on Exhale.

## Repository layout

Application code is in `exhale/`, with `exhale/__main__.py` as the main entry
point. Widget-independent project, channel, source, and settings models are
grouped in `exhale/data/`. Image composition, display, and image-specific
controls are grouped in `exhale/imaging/`. Analysis execution, persistence,
and result visualization are grouped in `exhale/analysis/`. Saved-project
persistence, lifecycle policy, and project controls are grouped in
`exhale/project/`. The imported numerical implementation remains in
`exhale/xrf_refcopy/`.
Tests are in `tests/`.

Feature controllers own their mutable UI state, including selections, workers,
threads, and derived views. `MainWindow` coordinates application-wide signals,
while controllers communicate through their public interfaces.

Source-file selection, opening, removal, and relocation belong to
`SourceManager`. Project-directory creation, loading, and saving belong to
`ProjectManager`. Actions and callers connect directly to the manager responsible
for each workflow.

Bundled icons, Qt Designer files, and model data belong in
`exhale/resources/`. Packaging files belong in `packaging/`, and release
automation is in `.github/workflows/`.

Editable and generative artwork sources are stored in `artwork/`.
Application-ready runtime images are stored in `exhale/resources/`, while generated
platform containers such as the current `.ico` and `.icns` files are stored in
`packaging/icons/`. The retained artwork
layout and XRF generation procedure are described in
[`code-overview.md`](code-overview.md) and
`artwork/generate/xrf_cells_x_imagegen_prompt.md`.

## Python style and tooling

Exhale supports Python 3.11 through 3.13. Hand-written Python uses four-space
indentation, `snake_case` for functions, variables, and modules, and
`PascalCase` for classes. Keep imports at the top of a module. Use a
100-character line length, double-quoted strings, and trailing commas in
multiline constructs.

Ruff is the formatter and style checker. Its formatting decisions take
precedence over manual line arrangement unless they cause a clear readability
problem. Review fixes by rule, keep mechanical changes separate from semantic
changes, and limit suppressions to the narrowest practical scope. Explain
non-obvious suppressions.

Run read-only checks from the repository root with:

```bash
python -m ruff format --check .
python -m ruff check .
```

Both commands must pass before handing off a code change. They operate on the
maintained Python source in the repository; generated `*_ui.py` modules are
excluded by `.ruff.toml`.

To apply formatting after reviewing its scope, run `python -m ruff format .`.
Ruff can apply individually reviewed lint fixes with `python -m ruff check
--fix --select RULE .`.

The lint policy covers Python errors and warnings, unused names, import ordering,
common bugs, supported syntax modernization, obsolete suppression comments, and
the preview `E30x` structural blank-line rules. Additional rules are adopted when
they address a demonstrated problem in this codebase.

Unicode in strings and tuple concatenation for immutable JSON paths are
intentional, so the Ruff configuration excludes the ambiguous-Unicode (`RUF001`)
and collection-literal-concatenation (`RUF005`) rules.

The repository-local `.ruff.toml` is authoritative. Keep its target version,
generated-file exclusions, and selected rules consistent with this document.

## Documentation

[`architecture.md`](architecture.md) describes durable component boundaries
and ownership. [`code-overview.md`](code-overview.md) lists every maintained
source module and its responsibility. Update both documents in the same change
when modules are added, removed, renamed, or given substantially different
responsibilities.

Every maintained Python module needs a module docstring which states its role.
Major models,
controllers, workers, reusable widgets, and public functions need concise
docstrings describing their contract. Document private helpers when their
state changes, constraints, error behavior, or relationship to another
component is not apparent from the signature and immediate context. Trivial
accessors, direct signal forwarders, and ordinary Qt overrides do not need
ceremonial docstrings.

Use concise PEP 257 summaries. Type annotations provide the type documentation.
Add parameter, return-value, exception, ownership, mutation, or callback details
when they convey information not evident from the signature. Comments explain
reasons, invariants, and external constraints.

For generated `*_ui.py` modules, document the corresponding Designer file or
controller.

## Scope of changes

Prefer small, local changes over architectural rewrites. Preserve existing
behavior unless the task requires otherwise, and keep refactoring related to
the task at hand. Keep user-facing text clear. Treat resource paths as part of
the packaged application interface.

Use the simplest UI rule that implements the requested behavior. Do not add
special cases, inferred layout policies, or novel interactions without first
establishing that they are needed.

Resolve open design questions before adding GUI controls, terminology, workflows,
or automatic behavior. Preserve standard widget behavior, including focus,
selection, and item position, unless a feature requires otherwise. Show changing
user data in its own field or in the content view rather than building long labels
from headings, separators, and values.

Write interface help for a reader who knows the application's task but has not
read the development conversation. Explain the quantities and assumptions the
reader needs to interpret results. Do not include references to abandoned
designs, implementation details, or qualifications whose relevance exists only
in chat history. Describe spatial restrictions in terms of the visible data,
rather than array or mask operations. Retain the methodological information
needed to reproduce calculations, expressed in the reader's terms.

## Qt and generated code

Access Qt through `qtpy` so the application remains independent of a specific
Qt binding.

The packaged binding is PyQt6 (Qt 6.7 or newer), required by Napari 0.10.
The launcher and dependency-trial tool default `QT_API` to `pyqt6` so older
bindings left in a development environment are not selected accidentally.
When running pytest directly in such an environment, use `QT_API=pyqt6`.

Establish sorting and grouping when a list or selector is populated, then keep
item positions stable while the user selects, checks, activates, or edits items.

Main content splitters use an 8-pixel handle width, as established on the
Project data and Element maps tabs. This provides the extra space needed for a
splitter without changing the normal margins around its panes. Embedded canvas
or viewer widgets that must align with adjacent pane contents should use zero
internal layout margins; keep the tab's normal outer margins intact.
After adding, removing, or replacing a container widget, inspect all four edges
of the affected panes at normal display scale. Each pane should retain the
application's normal outer margin without acquiring a second margin or frame.
Replacing a framed container should preserve the spacing around it. Compare
alignment with adjacent panes as well as the layout property values.

Files in `exhale/resources/ui/` are the Qt Designer sources for the generated
`exhale/*_ui.py` modules. Make UI changes in the corresponding `.ui` file and
regenerate the Python modules with:

```bash
./run_exhale.py --recompile-only
```

This recompiles every UI Python module and exits without starting the application.
The regeneration code in `exhale.__main__._recompile_ui` rewrites generated
binding-specific imports to use `qtpy`.

Keep static tooltip text in `exhale/tooltips.py`, grouped by its owning window
or dialog, and apply catalogue entries by stable Qt object name so stale names
fail during setup. Tooltips which depend on
runtime state may remain beside the behavior which updates them, while their
static text variants should still be defined in the catalogue.

## Data model invariants

`ElementRef` is the stable identity for selectable source data and replaces raw
`(filename, dataset_path)` identity tuples.

An image slot normally refers to its sample's `ElementSettings`, so edits
to sample settings propagate to images using them. An image-local override
is an explicit copy recorded in `ImageSettings.element_overrides`; changes to
that copy remain local to the image. Code handling image elements preserves
this distinction and the corresponding channel key.

`ProjectData` owns all saved project objects, including composed-image
settings. Persistence code operates exclusively on that model. After a model has
been loaded, project lifecycle controllers refresh the interface and coordinate
its selections and signals.

Downstream computations that use segmentation must retain a `SegmentationReference`
with their output, including its post-processing settings. Compare it with the
consumer's chosen input to determine whether output is outdated; do not infer the
input from whichever mask is currently displayed. Resolve the recorded revision
without substituting another mask, and never silently recompute stored output.
The current element clustering does not consume segmentation.

## Running and testing

Run commands from the repository root. The usual entry points are:

```bash
python run_exhale.py
./run_exhale.py --help
./run_exhale.py --startup-check
python -m pytest
```

The startup check constructs `MainWindow` without creating the OpenGL canvas,
imports the Napari integration and segmentation backends, verifies the DINOv3
constructor, reports
the runtime versions used by the About dialog, and exits without showing the
main window. The manually dispatched **Windows startup check** workflow runs it
from the installed package for each backend selection. Windows installer builds
run the same check through the installed native launcher after Inno Setup has
created the private uv environment.

Every change should at least pass `./run_exhale.py --help` and focused tests for
the affected code. Add tests under `tests/`, named `test_<feature>.py`, when a
behavior can be tested non-interactively.

GUI changes also require interactive testing with representative data. A
successful application startup does not validate the changed workflow.

## Trying dependency updates on Linux

Run `python tools/try_dependency_updates.py` from the normal development
Python environment, with uv available on PATH. It creates a fresh environment
under `.dependency-trials/`, using the current Python interpreter, and installs
the latest compatible stable runtime dependencies without Exhale's version
bounds. Upstream dependency requirements still apply. Documented exceptions in
`[tool.dependency-trial.keep]` retain their declared requirements; the pinned
DINOv3 source in `requirements-cellpose.txt` is also retained.

The tool records the requested requirements and exact installed versions in the
trial directory, runs Ruff, the startup check and pytest, then launches the GUI
for manual testing if all checks pass. Automated checks use Qt's offscreen
platform; the GUI uses the normal display. Choose `--backends none|stardist|cellpose|both` for a new trial (default: both).
Only Cellpose trials install the DINOv3 requirements file.
Use `--no-gui` for automated checks
alone. The checkout is run directly, so source changes are available immediately.
Use `--environment PATH` to rerun checks and launch an existing trial without
reinstalling its dependencies. The environment can also be used directly through
`PATH/bin/python run_exhale.py`.

For work with Codex, ask it to run a dependency trial, inspect failures, and make
any needed source changes. After manual testing, ask it to update the Linux
requirements in `pyproject.toml` using the recorded versions. These metadata
changes are reviewed separately; the tool does not accept updates automatically.
For conventional major.minor.patch releases, testing 1.2.3 normally establishes
`>=1.2.3,<1.3`; packages with different version conventions need individual bounds.

## Compatibility during development

Saved projects use a current writer and a structurally tolerant reader. Unknown
fields are ignored, absent nonessential fields use their current defaults, and
independent objects such as images or analysis results may be skipped when the
rest of the project remains usable.

The project format identifier and the core sample/asset structure remain
mandatory. Files written by a newer project version are rejected because their
semantics are unknown. Older versions are loaded directly with the current
structural reader. Recoverable problems are reported together after loading. A
project is marked dirty when defaults or omissions make its current state differ
from the file, so the next save writes the current format.

When an internal format changes, update the writer, reader, and tests together.
Use field defaults and independent-object failure handling for development
formats. Explicit migrations are reserved for established compatibility
requirements.

## Git and releases

Routine development takes place on `main`; a separate development branch is
not required. Commits are useful checkpoints, and `main` need not always
correspond to a released version. Use short, imperative, sentence-case commit
subjects, such as `Minor cleanup` or `Element name edit propagates`.

Stable releases are made with:

```bash
./version_bump.sh major|minor|patch
```

The script creates and pushes a release commit and tag. The tag starts the
GitHub workflow that publishes to PyPI and builds the Windows and macOS
artifacts. It is the final step when intentionally creating a release.


## Trained-model distribution

Large segmentation weights are GitHub release assets, independently versioned
from Exhale releases. Software version lookup matches only `v[0-9]*` tags, so
model-release tags cannot become application versions. `exhale/analysis/model_store.py` records the exact URL,
expected byte size and SHA-256. Models are fetched only when needed for a run;
StarDist continues using its bundled model. User-selected model storage belongs
to application settings, never project state.

The first Cellpose asset is prepared for release tag `models-v1` in the existing
`ctroein/exhale` repository. Prepare it without installing Exhale or publishing:

```bash
python tools/prepare_model_release.py /path/to/nuclei_cellpose /path/to/release-assets
```

The command checks the source contents and creates the model asset, a `.sha256`
file, JSON metadata and the DINOv3 license under `cellpose-dino-xrf/1/` in the destination. The release
asset must retain its basename `cellpose-dino-xrf-v1.pt`. Publication is a separate,
explicitly authorized operation; the configured public URL returns HTTP 404 until
that release asset is published. Changing trained weights requires a new model
version, checksum and versioned asset URL rather than silently replacing a file.

Source and installed applications share the same cache layout and validation.
Transfer tests use a local HTTP server to cover truncated responses, checksum
failures, cancellation and offline reuse without requiring public release assets.


## Segmentation dependencies and installers

`pyproject.toml` provides `stardist` (TensorFlow) and `cellpose` (PyTorch,
TorchVision and Cellpose 4.2.1.1) extras. The base application needs neither. DINOv3 is supplied through `requirements-cellpose.txt`, pinned to an
upstream source commit and archive SHA-256 because it is not published on PyPI.
For pip installation, pass that requirements file alongside `exhale-xrf`; for
a source checkout, install the file into the existing development environment.
The URL in the README lets pip retrieve it directly from this repository.

Native installers and Windows startup-check workflows use the same requirements
file when Cellpose is selected. Dependency wheels supply their own resource data
and metadata. Large trained weights stay in the model store and are not bundled
with the executable.
The startup check validates installed backends, rejects partial installations,
and skips absent backends. For Cellpose it verifies that its DINOv3 constructor
is available without loading or downloading any trained model.

The DINOv3 license is included under `exhale/resources/licenses/` and copied beside
the model release asset by `prepare_model_release.py`; publish it with that asset.
Third-party dependencies retain their own licenses, independently of Exhale's MIT
license. The old combined XRF processing and StarDist callers are removed; the
legacy containers remain only for clustering data and saved region tables.


## macOS setup application

`packaging/macos/build.py` builds an AppKit launcher from `Launcher.swift` and
packages it as an architecture-specific DMG. It includes the locally built EXHALE
wheel, the pinned DINOv3 requirements file, and uv 0.13.7. The builder checks the
uv archive against its upstream SHA-256 file. It uses ad-hoc code signing only;
there is no Developer ID or notarization and no signing secrets are needed.

The launcher targets macOS 13+. Dependency wheels may require a newer system;
current PyTorch wheels require macOS 14+ and Apple Silicon. Intel setup disables
Cellpose rather than attempting to install an unsupported PyTorch release.

On a Mac with Xcode command line tools, build with:

```bash
python -m build --wheel
python packaging/macos/build.py --wheel dist/exhale_xrf-VERSION-py3-none-any.whl
```

The output is `dist/EXHALE.app` and `dist/exhale-macos-ARCH.dmg`. Use a clean output
folder for each build. The user copies the app from the DMG into Applications.
The native launcher starts the bundled `runtime.py` using a private uv-managed
Python 3.12. Setup installs the bundled wheel with the selected extras in a new
private environment, runs `--startup-check`, then atomically switches its launch
record. Failed installations retain the old environment. Setup and launch hold
an exclusive lock; setup cannot replace or remove an environment in use.
Python, environments and cached downloads belong under
`~/Library/Application Support/EXHALE/runtime`; no shell configuration or shared
uv tools are changed. Downloaded model storage and project files are independent.

Hold Option at launch, or pass `--setup`, to show configuration and runtime
removal. Replacing the app triggers setup when the bundled wheel changes.
The setup app offers backend choices again using the previous selection.
Normal launches use the saved environment without resolving or upgrading packages.

GitHub Actions builds on both Apple Silicon and Intel runners. Its headless
entry point runs the same setup driver and startup checks as the GUI:

```bash
EXHALE_SETUP_HOME=/tmp/exhale-mac-test dist/EXHALE.app/Contents/MacOS/EXHALE --setup-check none
```

Use `stardist`, `cellpose`, or `both` instead of `none` for backend checks, subject
to architecture support. `EXHALE_SETUP_HOME` isolates test installations from user
state. The normal workflow tests base setup and the supported backends from the
packaged DMG before uploading it; manual `macos` builds need no release tag.
Linux tests cover backend selection, rollback, runtime ownership and locking.
The native Swift build and actual dependency installation require a Mac runner.
Interactive testing still needs to cover first launch from a downloaded DMG,
backend selection, launching with representative data, repair/update and removal.
Gatekeeper behavior must be checked on a real download, not inferred from CI.


## Windows uv installer

`packaging/win_build.py` builds an Inno Setup installer from a local EXHALE wheel,
a checksum-verified uv 0.13.7 executable and the native C# launcher in
`packaging/windows/Launcher.cs`. Building needs Windows, the .NET Framework C#
compiler included with Windows, and Inno Setup 6. Use a clean payload directory:

```powershell
python -m build --wheel
python packaging/win_build.py --wheel dist/exhale_xrf-VERSION-py3-none-any.whl
```

Pass `--iscc PATH` if ISCC.exe is not discoverable. The builder runs the launcher's
self-tests before compiling `packaging/exhale.iss`. Those tests include deletion
of a tree with paths longer than 300 characters: TensorFlow headers exceed the
legacy Windows path limit. The launcher enables modern .NET path handling and
uses extended paths for deletion without changing system policy. Cleanup visits
entries individually and reports the failing path, operation, attributes and
HRESULT. It removes junctions without traversing their targets. Native self-tests
check junction target preservation and diagnostics for a locked file as well as
long paths. Runtime packages are downloaded
on the target machine, rather than bundled into the installer. Python 3.11 is
used because Windows StarDist retains TensorFlow 2.15. The installer requires
64-bit-compatible Windows 10 or later and installs per-user without elevation.
No system Python, uv installation, shell edits or PowerShell policy changes are
needed. Default installation is under `%LOCALAPPDATA%/Programs/Exhale`.

Inno's component page selects StarDist, Cellpose, both or neither. Before copying
launcher files, `PrepareToInstall` extracts the bundled payload to a temporary
directory and calls `--prepare-install`. The launcher uses uv to build and check
a new environment in `{app}/runtime/env-UUID`; it records it as pending only after
`--startup-check` passes. `--activate-install` atomically publishes that record
after files are copied. Failed/cancelled preparation discards pending environments,
leaving the previous installed record intact. A fresh failed installation also
cleans its unused private runtime; `runtime.log` is retained for diagnostics.
Rerunning setup updates the application and can change the selected extras.

The launcher forwards ordinary arguments to its private `python -m exhale`,
streams output to `{app}/runtime.log`, and reports launch failures. An exclusive
runtime file lock protects setup and launch; an application mutex also prevents
Inno setup/uninstall while EXHALE is running. Before removing the launcher and shortcuts, Inno calls `--remove-runtime` to
delete the private runtime using extended paths. A cleanup failure aborts
uninstallation and retains the launcher and its diagnostic log for retry. User projects, settings and trained-model storage remain
independent. An old `_internal` directory is removed when upgrading a legacy
bundled installation.

The GitHub `windows` build runs `packaging/windows/test-installer.ps1` against the
actual installer. It installs each backend combination in a path containing
spaces, changes selections through upgrades, checks the resulting dependency
presence, runs the installed launcher with `--startup-check`, then silently
uninstalls and checks runtime removal. Logs are retained as workflow artifacts,
including on failure. The separate Windows startup-check workflow still tests
ordinary pip installations, without building an installer or creating a release.
A manual `windows` build needs no tag. Native compilation, Inno execution and
these integration checks require a Windows runner; Python tests on Linux cover
payload metadata and download integrity. Interactive Windows testing should
exercise the component page, download/error feedback, shortcuts, representative
data, changing backends and the Settings uninstall entry.

The old PyInstaller builds and hooks have been removed on all platforms. Linux
uses uv directly; macOS uses its native setup app and private uv runtime.
