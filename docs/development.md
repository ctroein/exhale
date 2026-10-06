# Exhale development conventions

This document describes the conventions and invariants for work on Exhale.

## Repository layout

Application code is in `exhale/`, with `exhale/__main__.py` as the main entry
point. Domain-specific code is grouped in `exhale/cluster_analysis/` and
`exhale/xrf_refcopy/`. Tests are in `tests/`.

Bundled icons, Qt Designer files, and model data belong in
`exhale/resources/`. Packaging files belong in `packaging/`, and release
automation is in `.github/workflows/`.

## Python style and tooling

Exhale requires Python 3.10 or newer. Hand-written Python uses four-space
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

The intended lint policy covers Python errors and warnings, unused names,
import ordering, common bugs, supported syntax modernization, obsolete
suppression comments, and the preview `E30x` structural blank-line rules.
Naming, complexity, security, blanket documentation, simplification, and broad
Ruff-specific rule collections are not part of the policy. Add rules only to
address a demonstrated problem in this codebase.

Unicode in strings and tuple concatenation for immutable JSON paths are
intentional. Do not enable Ruff's ambiguous-Unicode (`RUF001`) or
collection-literal-concatenation (`RUF005`) rules.

No Ruff configuration is currently committed, so these rules cannot yet be
run reproducibly. Until one is added, match nearby code and avoid repository-
wide formatting changes.

## Scope of changes

Prefer small, local changes over architectural rewrites. Preserve existing
behavior unless the task requires otherwise, and avoid unrelated refactoring.
Keep user-facing text clear and do not change resource paths incidentally;
packaged applications depend on them.

## Qt and generated code

Access Qt through `qtpy`, not through a specific Qt binding.

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

An `ElementSettings` stored in an `ImageSettings` is intentionally a copy.
Changes to image-local element settings must not propagate accidentally to
global element settings. Code that handles an `ElementSettings` should make it
clear which kind it is and preserve the existing propagation semantics.

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

Until a release is explicitly declared stable and supported, Exhale provides
no backward compatibility for saved projects, autosaves, persistent
application settings, or other internal on-disk formats. This is development
software without an installed user base; compatibility code and migrations
would add maintenance cost without serving a user.

When an internal format changes during development, update the writer, reader,
and tests together. Remove obsolete fields and readers instead of accepting
both the old and new representations. Existing development data may be
discarded. Do not add migrations, legacy-key fallbacks, deprecated aliases, or
version-dependent branches unless a specific external compatibility
requirement has first been agreed.

Compatibility begins only when a release is explicitly declared stable and
supported. That declaration must also replace this section with the agreed
compatibility scope and support policy.

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
