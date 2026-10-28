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

## Running and testing

Run commands from the repository root. The usual entry points are:

```bash
python run_exhale.py
./run_exhale.py --help
./run_exhale.py --startup-check
python -m pytest
```

The startup check constructs `MainWindow` without creating the OpenGL canvas,
imports the Napari integration, TensorFlow, and the StarDist integration, reports
the runtime versions used by the About dialog, and exits without showing the
main window. The manually dispatched **Windows startup check** workflow runs it
from the installed package. Release builds run the same check against the frozen
Windows application after PyInstaller finishes.

Every change should at least pass `./run_exhale.py --help` and focused tests for
the affected code. Add tests under `tests/`, named `test_<feature>.py`, when a
behavior can be tested non-interactively.

GUI changes also require interactive testing with representative data. A
successful application startup does not validate the changed workflow.

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
