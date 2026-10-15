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

Bundled icons, Qt Designer files, and model data belong in
`exhale/resources/`. Packaging files belong in `packaging/`, and release
automation is in `.github/workflows/`.

## Python style and tooling

Exhale requires Python 3.11 or newer. Hand-written Python uses four-space
indentation, `snake_case` for functions, variables, and modules, and
`PascalCase` for classes. Keep imports at the top of a module. Use a
100-character line length, double-quoted strings, and trailing commas in
multiline constructs.

Ruff is the intended formatter and style checker. Its formatting decisions
take precedence over manual line arrangement unless they cause a clear
readability problem. Do not apply `ruff check --fix` indiscriminately: review
findings by rule, keep mechanical changes separate from semantic changes, and
suppress findings only at the narrowest practical scope. Explain non-obvious
suppressions.

Run read-only checks from the repository root with:

```bash
python -m ruff format --check .
python -m ruff check .
```

Both commands must pass before handing off a code change. They operate on all
hand-written Python in the repository; generated `*_ui.py` modules are excluded
by `.ruff.toml`.

To apply formatting after reviewing its scope, run `python -m ruff format .`.
Ruff can apply individually reviewed lint fixes with `python -m ruff check
--fix --select RULE .`; do not use an unrestricted `--fix` pass.

The intended lint policy covers Python errors and warnings, unused names,
import ordering, common bugs, supported syntax modernization, obsolete
suppression comments, and the preview `E30x` structural blank-line rules.
Naming, complexity, security, blanket documentation, simplification, and broad
Ruff-specific rule collections are not part of the policy. Add rules only to
address a demonstrated problem in this codebase.

Unicode in strings and tuple concatenation for immutable JSON paths are
intentional. Do not enable Ruff's ambiguous-Unicode (`RUF001`) or
collection-literal-concatenation (`RUF005`) rules.

The repository-local `.ruff.toml` is authoritative. Keep its target version,
generated-file exclusions, and selected rules consistent with this document.

## Documentation

[`architecture.md`](architecture.md) describes durable component boundaries
and ownership. [`code-overview.md`](code-overview.md) lists every hand-written
source module and its responsibility. Update both documents in the same change
when modules are added, removed, renamed, or given substantially different
responsibilities.

Every hand-written Python module needs a module docstring which states its
role; creation dates and filenames are not documentation. Major models,
controllers, workers, reusable widgets, and public functions need concise
docstrings describing their contract. Document private helpers when their
state changes, constraints, error behavior, or relationship to another
component is not apparent from the signature and immediate context. Trivial
accessors, direct signal forwarders, and ordinary Qt overrides do not need
ceremonial docstrings.

Use concise PEP 257 summaries. Type annotations are the authoritative type
documentation, so do not repeat them in prose. Add parameter, return-value,
exception, ownership, mutation, or callback details only when they convey
information not evident from the signature. Comments explain reasons,
invariants, and external constraints rather than restating the following code.

Generated `*_ui.py` modules are excluded from source-documentation
requirements. Document the corresponding Designer file or controller instead.

## Scope of changes

Prefer small, local changes over architectural rewrites. Preserve existing
behavior unless the task requires otherwise, and avoid unrelated refactoring.
Keep user-facing text clear and do not change resource paths incidentally;
packaged applications depend on them.

Do not invent GUI controls, terminology, workflows, or automatic behavior to
fill an unresolved design gap. Implement only interactions established in the
task or existing interface; leave undecided functionality absent until it has
been discussed. Preserve standard widget behavior, including focus, selection,
and item position, unless a requested feature explicitly requires otherwise.
Do not construct long interface labels by concatenating user data with headings,
separators, or explanatory text. Show changing user data in its own field or in
the content view where it belongs.

## Qt and generated code

Access Qt through `qtpy`, not through a specific Qt binding.

Do not reorder choices in a list or selector in response to selecting,
checking, activating, or editing one of them. Establish any sorting or grouping
when the view is populated, then keep item positions stable during ordinary
interaction with that view.

Main content splitters use an 8-pixel handle width, as established on the
Project data and Element maps tabs. This provides the extra space needed for a
splitter without changing the normal margins around its panes. Embedded canvas
or viewer widgets that must align with adjacent pane contents should use zero
internal layout margins; keep the tab's normal outer margins intact.
After adding, removing, or replacing a container widget, inspect all four edges
of the affected panes at normal display scale. Check that each pane retains the
application's normal outer margin, that nested layouts do not add a second
margin or frame, and that replacing a framed container has not accidentally
removed the spacing which belonged around it. Compare alignment with adjacent
panes rather than relying only on layout property values.

Files in `exhale/resources/ui/` are the Qt Designer sources for the generated
`exhale/*_ui.py` modules. Never edit, format, or repair generated UI modules
directly. Change the corresponding `.ui` file and regenerate the Python module
with:

```bash
./run_exhale.py --recompile
```

The regeneration code in `exhale.__main__._recompile_ui` rewrites generated
binding-specific imports to use `qtpy`.

## Data model invariants

`ElementRef` is the stable identity for selectable source data. New code must
not reintroduce raw `(filename, dataset_path)` tuples as identities.

An image slot normally refers to its sample's `ElementSettings`, so edits
to sample settings propagate to images using them. An image-local override
is an explicit copy recorded in `ImageSettings.element_overrides`; changes to
that copy must not propagate back to the sample. Code handling image
elements must preserve this distinction and the corresponding channel key.

## Running and testing

Run commands from the repository root. The usual entry points are:

```bash
python run_exhale.py
./run_exhale.py --help
python -m pytest
```

Every change should at least pass `./run_exhale.py --help` and focused tests for
the affected code. Add tests under `tests/`, named `test_<feature>.py`, when a
behavior can be tested non-interactively.

GUI changes also require interactive testing with representative data. A
successful application startup does not validate the changed workflow.

## Compatibility during development

Saved projects use a current writer and a structurally tolerant reader. Do not
build chains of version-specific migrations for development formats. Unknown
fields are ignored, absent nonessential fields use their current defaults, and
independent objects such as images or analysis results may be skipped when the
rest of the project remains usable.

The project format identifier and the core sample/asset structure remain
mandatory. Reject files written by a newer project version, since their
semantics are not known. Attempt to load older versions directly with the
current structural reader. Report recoverable problems together after loading
and mark a project dirty when defaults or omissions make its current state
differ from the file, so the next save writes the current format.

When an internal format changes, update the writer, reader, and tests together.
Prefer field defaults and independent-object failure handling over version
branches, renamed-field aliases, or transformation code. Add an explicit
migration only when a real compatibility requirement justifies maintaining it.

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
artifacts. Run it only when intentionally creating a release.
