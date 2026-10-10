# Improvement plan: usability, complexity, and agent navigation

- Created: 2026-10-10, from the findings in the "Audit 2026-10-10" section of
  `docs/CODEBASE_AUDIT.md`
- Baseline: 200 tests passing at revision `0c300de`, plus ruff and mypy from
  Phase 0
- Companion docs to update per phase: `docs/CODEBASE_AUDIT.md`,
  `docs/CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md`, `README.md`, and
  `.portfolio/architecture.md`
- Scope decisions: user-facing bugs are fixed, not just documented; a future
  full CLI redesign is captured as a design brief in Phase 5 rather than
  implemented here; dev-only tooling is allowed; no SQLite schema changes

## Ground rules for every phase

1. `tests/fixtures/complex_c_project` is not modified. It is cintel's own test
   subject; its expected findings and validators define correct behavior.
2. The full suite passes before and after every phase. Behavior changes are
   allowed only where a phase says so, and each one lands with a test that
   failed before the change.
3. No SQLite schema version bump. Stored state written by earlier versions
   stays readable.
4. No new runtime dependencies.
5. Each phase ends by updating this file's status, the audit doc if findings
   land, `README.md` if user-visible commands or outputs change, and the
   roadmap doc.
6. Phases are independently shippable. Land one, commit, move on.

## Phase 0: tooling and a written record

Status: complete (2026-10-10)

Landed:

- The `pyproject.toml` dev extra now includes `ruff` and `mypy`.
- Ruff config: target py311, rules `E4`, `E7`, `E9`, `F`, `I`, `UP`, `B`,
  `SIM`, with `tests/fixtures` excluded.
- Mypy config: `check_untyped_defs`, `warn_unused_ignores`,
  `warn_redundant_casts`, `no_implicit_optional`, checking `src/cintel`.
- First run: 147 ruff autofixes (import order, `datetime.UTC`,
  `collections.abc` imports, quoted annotations, unused imports) plus manual
  fixes for eight undefined annotation names and one shadowed loop variable in
  `adapters/reports/repository.py`, an overly-broad `dict[str, object]` return
  in `application/queries.py`, missing `FunctionSymbol` narrowing in query and
  report services, list typing in `gcc_arguments.py` and `presentation.py`,
  `Literal` overloads for `source_relationship_from_dict`, and one documented
  `type: ignore[type-var]` on `replace_fields` where mypy cannot type
  `dataclasses.replace` through a generic wrapper.
- `.github/workflows/quality.yml` runs ruff, mypy, and the test suite on pushes
  to `main` and on pull requests.
- README documents the ruff and mypy commands.
- The re-audit is written up in `docs/CODEBASE_AUDIT.md`.
- Not adopted: `ruff format`. 86 files would change; it gets its own phase if
  the maintainer wants it.

Verification: `ruff check src scripts tests` clean, `mypy` clean over 62
source files, 200 tests green.

## Phase 1: failure-path tests

Status: complete (2026-10-10)

Landed:

- `tests/integration/test_cli_contracts.py` (11 tests): missing repository for
  `scan`, `doctor`, and `report`; malformed `--config`; corrupt SQLite; a
  too-new schema; doctor's unwritable-output diagnostic; and out-of-order
  `report`, `symbols`, `context`, and `build units`.
- `tests/unit/test_presentation.py` gained 20 tests covering
  `render_initialization`, `render_scan`, `render_symbols`,
  `render_function_detail` including the candidates and empty-relationship
  branches, `render_call_sites`, `render_context_result`, `render_report_run`,
  and the `_json` helpers.
- `tests/unit/test_input_artifacts.py` gained 9 tests: missing source,
  unreadable source, copy failure, unreadable preserved file, missing
  preserved file, changed source, and the validation failure and warning
  branches.
- `tests/unit/test_guidance.py` gained 6 tests: the file-list fallback,
  default make names without a configuration, missing-source search
  instructions, both renderer error branches, and the empty-instruction text.
- `tests/unit/test_doctor.py` gained a missing-tool test using a new
  `UnavailableFakeRunner`.
- `tests/unit/test_serialization.py` gained unsupported-kind and
  `json_default` error tests.
- `tests/unit/test_architecture.py` (3 tests) enforces import direction:
  layers import only inward, only the command runner imports `subprocess`, and
  only storage modules import `sqlite3`.
- One source fix, surfaced by the corrupt-database test:
  `application/storage_session.py` now closes the storage adapter when
  `initialize` raises. The old code leaked an open `sqlite3.Connection` on
  every failed initialize.

The probes written for these tests corrected two audit findings: `analyze` on
a missing repository raises an uncaught `IntegrityError` rather than exiting
0, and an unwritable output directory crashes `scan` with an uncaught
`PermissionError`. Both are recorded in the audit and targeted by Phase 2.

Verification: 253 tests pass (210 unit, 43 integration), ruff and mypy clean,
`tests/fixtures/complex_c_project` untouched.

## Phase 2: user-friendliness fixes

Status: pending

Each fix lands with a test that failed before it.

- `analyze` on a missing or unscannable root propagates the scan error, exits
  2, and never opens storage. Today it raises an uncaught `IntegrityError`
  after creating the workspace (`application/analysis.py:100`,
  `application/scanning.py:46-50`).
- Workspace write failures produce a `StorageError` and exit 2 instead of an
  uncaught `PermissionError`; `SQLiteAnalysisStorage.initialize` catches
  `OSError` as well as `sqlite3.Error` (`adapters/storage/sqlite.py:61-80`).
- Split not-found from ambiguous. A new `FunctionNotFound` result makes
  `show function`, `callers`, `callees`, and `context function` tell an empty
  index apart from duplicate definitions, with a hint to run `cintel analyze`
  first. Exit 1 stays for empty results, per the documented contract.
- `build units` with nothing discovered exits 1 and hints at
  `cintel build discover`.
- `symbols`, `report`, and `context` print prerequisite hints when no analysis
  state exists.
- `--budget` is validated in argparse so invalid values produce a usage error
  instead of a traceback.
- `build discover` honors `--input-type`; `setup` and `instructions` reject
  `--input-file` with a message pointing at `resume`.
- Help overhaul: help text for every option, epilogs with examples, an
  explicit note that global options come before the subcommand, and the
  `--build-config` default documented.
- `--json` errors print a structured error object.
- One shared diagnostic formatter in `cli/presentation.py` that includes
  `suggested_actions`, used by scan, build, analysis, and report renderers.
- Non-TTY `make -n` always prints the evaluation command and the
  `$(shell ...)` warning to stderr.
- `_resolve_config`: `--config` wins; `--output-directory` overrides a loaded
  conventional config instead of discarding it.
- `init` accepts a fallback repository from `--repository` or the current
  directory when the positional is omitted.
- `start.sh`: quote `$REPO` in next steps, fall back to file-scoped analysis
  when Make discovery fails, guard option 2, and stop swallowing analyze and
  report failures. Also rebuild the venv when its interpreter or pip is
  unhealthy; a system Python upgrade left this checkout's venv with a 3.14
  interpreter and 3.12 site-packages, and the current reuse check accepted it.

Verification: suite green, `ruff` and `mypy` clean, manual CLI pass over the
fixture for each changed command.

## Phase 3: complexity reduction

Status: pending

- Split both renderer classes into one module per report family under
  `adapters/reports/markdown/` and `adapters/reports/json/`, with shared table
  and glossary helpers. Public class names stay. Verify byte-identical output
  for all report families against a pre-change snapshot.
- Split `SQLiteAnalysisStorage` into a package: connection handling, a
  repository and file store, a build store, an analysis store, and a workflow
  and report store, with a facade keeping the current class name and
  constructor signature. Verify with an A/B dump of every table for the fixture
  repository. No schema change.
- Break `SourceAnalysisService.analyze` into named phases and move
  `_capabilities` to its own module.
- Deduplicate the function-definition filter in `application/queries.py` and
  split `_select_definition` into collapse, not-found, and ambiguous cases.
- Ratchet mypy: remove the `replace_fields` ignore if a clean pattern appears,
  and keep the config unchanged otherwise.

Verification: suite green, A/B dumps byte-identical, ruff and mypy clean.

## Phase 4: agent navigation

Status: pending

- New `AGENTS.md` with the layer map, command flows, invariants, test
  commands, the fixture rule, where state lives on disk, and a doc map. Keep it
  short and link to existing docs instead of duplicating them.
- Module docstrings for every module, ports and application services first.
- Class and method docstrings for the port protocols, application services,
  the storage adapter's public surface, and the CLI entry points.
- Why-comments at the non-obvious points in `conservative.py`, `sqlite.py`,
  `adapters/reports/repository.py`, and `make.py`: masking strategy,
  call-resolution ordering, budget cutoff, fingerprint semantics, projection
  columns, and monotonic resolution.

Verification: docstring coverage check passes, suite green.

## Phase 5: documentation sync and redesign brief

Status: pending

- Fix `README.md`: the fixture section, guided recovery tense, a current
  command list, an exit-code section, and the global-option placement rule.
- Update `docs/CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md` with the new test
  count and remove the stale audit items at lines 481-495. Update
  `.portfolio/architecture.md` so its data flow covers analysis, queries,
  context, and reports.
- New `docs/CLI_REDESIGN_BRIEF.md` covering the future full redesign: global
  options accepted after subcommands via argparse parents, a `cintel status`
  command, auto-run versus hint decisions for prerequisites, a unified JSON
  envelope with error objects, config precedence rules, a naming pass across
  `show`, `symbols`, and `build`, an interactive wizard beyond `start.sh`, and
  shell completion. The brief stays a design document until the maintainer
  picks it up.

Verification: docs match behavior; no code changes.

## Definition of done

All six phases landed, suite green throughout, fixture untouched, ruff and
mypy clean, and the docs describe the tool as it actually behaves. The
codebase then has two mega-classes split by job, failure paths covered by
tests, a written CLI redesign direction, and enough module-level documentation
for an agent to navigate without reading every file.
