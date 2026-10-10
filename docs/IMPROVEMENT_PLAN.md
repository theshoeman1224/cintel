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

Status: complete (2026-10-10)

Landed, each with a regression test:

- `analyze` on a missing or unscannable root raises `ConfigurationError`
  before opening storage, so the CLI exits 2 with the scan error and no
  workspace appears under the bad path. Previously it raised an uncaught
  `IntegrityError` after creating the database.
- `SQLiteAnalysisStorage.initialize` catches `OSError` as well as
  `sqlite3.Error`, so an unwritable output directory exits 2 with
  `Unable to initialize ...` instead of an uncaught `PermissionError`.
- A new `FunctionNotFound` result separates an absent name from duplicate
  definitions across `show function`, `callers`, `callees`, and
  `context function`. Empty results still exit 1, and the message points at
  `cintel analyze` when the index is empty. `--file` with no matching
  definition now reports not-found rather than ambiguity.
- `build units` with nothing discovered exits 1 and points at
  `cintel build discover`.
- `symbols` and `report` print a `cintel analyze` hint when no analysis state
  exists. `ReportRunResult` gained `analysis_present`, and the report text
  warns before readers rely on empty symbol and call-graph families.
- `--budget` is validated by argparse, so zero and non-numeric values produce
  a usage error instead of a traceback.
- `build discover --input-file` honors `--input-type`. `setup` and
  `instructions` reject `--input-file` with a message pointing at `resume`.
- Help text covers every previously bare option, the `--build-config` default,
  and every positional. A top-level epilog states that global options come
  before the subcommand.
- `--json` errors print a structured `{"error": {...}}` object instead of
  plain stderr text.
- Scan, build, analysis, and report renderers share one diagnostic formatter
  that includes `suggested_actions` as `Action:` lines.
- Non-TTY `make -n` always prints the evaluation command and the
  `$(shell ...)` warning to stderr, not only with `--verbose`.
- `_resolve_config` lets `--output-directory` override a loaded conventional
  config instead of discarding the config.
- `init` accepts `--repository` or the current directory when the positional
  is omitted.
- `start.sh`: quotes repository paths in next steps, falls back to file-scoped
  analysis when Make discovery or evidence import fails, surfaces analyze and
  report exit codes instead of swallowing them, avoids the `head` pipe under
  `pipefail`, and rebuilds the venv when its pip is unhealthy. The last one
  came from this checkout's own broken venv after a system Python upgrade.

Verification: 272 tests pass (220 unit, 52 integration), ruff and mypy clean,
`tests/fixtures/complex_c_project` untouched.

## Phase 3: complexity reduction

Status: complete (2026-10-10)

Landed:

- `MarkdownReportRenderer` split into `adapters/reports/markdown/`, one module
  per report family, with `shared.py` holding the table-of-contents helpers
  (`require`, `escape`, `build_awareness_markdown`). The class keeps its name
  and dispatch surface. The JSON renderer moved to
  `adapters/reports/json_renderer.py` as one module instead of ten: its family
  methods are 7 to 10 lines each, so per-family files would add navigation
  cost without reducing complexity. This is the one deviation from the
  original plan.
- `SQLiteAnalysisStorage` split into `adapters/storage/sqlite/`: `base.py`
  owns the connection and schema bootstrap, and `repository_store.py`,
  `build_store.py`, `analysis_store.py`, and `workflow_store.py` hold the
  methods for one aggregate each as mixins. `diagnostics.py` holds the shared
  diagnostic read/write helpers. The facade keeps the class name, constructor
  signature, and public methods, so composition and tests did not change.
  No schema change.
- `SourceAnalysisService.analyze` now orchestrates four named phases:
  `_analysis_inputs`, `_run_targets`, `_persist_relationships`, and
  `_record_analysis_state`. `_capabilities` moved to
  `application/analysis_capabilities.py` together with its status helpers.
- `application/queries.py`: `_definition_occurrences` replaces the duplicated
  definition filter in `function()` and `_definitions`; `_candidates` replaces
  three copies of the ambiguity result; `_select_definition` is now
  `_group_definitions` plus `_collapse_definition`.
- The `replace_fields` type ignore is gone. The wrapper now binds its TypeVar
  to a `_Dataclass` protocol with `__dataclass_fields__`, which mypy accepts
  without an ignore.

Verification: 272 tests pass, ruff and mypy clean over 81 files. All ten
Markdown families and their JSON siblings rendered byte-identical against a
pre-change snapshot of the complex fixture. Every table in the fixture
database was dumped before and after through a scan, query, and report
sequence; the only differences were temporary workspace paths and the two
timestamped repository-inventory hashes, both normalized for comparison.

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
