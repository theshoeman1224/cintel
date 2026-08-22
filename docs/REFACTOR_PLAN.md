# Refactor plan: cleanup milestones

- Created: 2026-08-22, from the findings in `docs/CODEBASE_AUDIT.md`
- Baseline: 64 tests passing at revision `945fca5`
- Companion doc to update per milestone: `docs/CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md`

## Ground rules for every phase

1. `tests/fixtures/complex_c_project` is not modified. It is cintel's own test
   subject; its expected findings and validators define correct behavior.
2. The full suite passes before and after every phase. No behavior change
   unless a phase says otherwise.
3. Each phase ends by updating this file's checkboxes, the roadmap doc if
   capabilities or wording changed, and `README.md` if user-visible commands
   or outputs changed. There are no build scripts beyond
   `scripts/install.py`; it needs updating only if packaging changes, which no
   planned phase does.
4. Phases are independently shippable. Land one, commit, move on.

## Phase 0: safety nets (tests only, no src changes)

Status: complete (2026-08-22)

The existing suite covers adapters well but leaves four interfaces exercised
only through higher-level flows, plus two untested paths entirely. Close these
before touching source.

Target interfaces to test:

1. `GuidedRecoveryService` directly with fake ports (scanner, artifact
   provider, storage factory). Cases: resume with no configuration;
   invalid-artifact path producing CI-INPUT-002; stale-artifact refresh
   producing CI-INPUT-003; artifact belonging to another build configuration;
   `instructions` regenerating REQUIRED_INPUTS.md without re-importing.
2. CLI presentation renderers (`cli/presentation.py`): text and JSON output of
   `render_doctor`, `render_recovery`, `render_build_discovery`,
   `render_compilation_units`. These are pure functions; tests are cheap.
3. Serialization round trips (`adapters/storage/serialization.py`) for every
   model kind written to SQLite, including the currently unwritten
   `CallRelationship` and `GlobalUsageRelationship` kinds and a `Diagnostic`
   carrying `related_commands` and `metadata`.
4. Schema migrations from v2, v3, and v4 snapshots up to v5. Only the v1 path
   has a test today.
5. `SubprocessCommandRunner` timeout behavior: a sleeping command must return
   exit code 124 with `timed_out` set and captured partial output.
6. Repository id stability: same root reached through different path
   spellings yields one id via the new shared helper (written first in Phase 1,
   so this test lands with it).

Landed as: `tests/unit/test_recovery_service.py` (7 tests),
`tests/unit/test_presentation.py` (8),
`tests/unit/test_serialization.py` (12),
`tests/unit/test_storage_migrations.py` (4), and one timeout test in
`tests/unit/test_command_runner.py`. Item 6 moves to Phase 1 as planned.
Suite now runs 96 tests (84 unit, 12 integration), all green.

## Phase 1: mechanical consolidation, zero behavior change

Status: complete (2026-08-22)

Findings addressed: 1 (repository identity), 2 (exclusion drift), 4's CLI
slice, 9's lifecycle boilerplate.

Landed as:

- `utilities.paths.stable_repository_id` is now the single repository-id
  derivation, used by scanning, initialization, build discovery (both sites),
  and recovery. Every site expands `~` and resolves before hashing.
- `utilities.paths.is_excluded` is the one exclusion matcher. Doctor's input
  detection now also skips excluded files per file, matching scan semantics;
  previously it only pruned directories and could count files that scan
  excludes. No fixture outputs change under default exclusions.
- `application.storage_session.storage_session` owns the
  initialize/try/finally-close lifecycle; scanning, initialization, build
  discovery (four methods), and recovery's `_storage` all delegate to it.
- `_diagnostics_exit_code` replaces the three inline error-exit rules for
  doctor, scan, and build discover. The resume exit rule stays status-based
  by design.
- New `tests/unit/test_paths.py` pins id stability across path spellings
  (trailing separators, dot-relative, symlinked, home-relative) and matcher
  semantics.

## Phase 2: decompose the conservative parser

Status: complete (2026-08-22)

Findings addressed: 4 (parse), 6 (tuple contracts), 7 (depth scanners), 8
(tag_matches), 9 (confidence numbers).

Landed as:

- `_AnalysisScope` owns scope id, fingerprint, timestamp, and a single
  `result()` builder; the three 14-field `SourceAnalysisResult`
  constructions collapsed into it. Failure paths now deduplicate like the
  success path, which is a no-op for their single diagnostic.
- `parse()` shrank to gating, reading, and phase calls;
  `_blank_directive_regions` and `_construct_outputs` hold the directive
  masking and per-construct dispatch that used to live inline.
- `_top_level_constructs` reports `_ConstructIssue` records instead of
  anonymous `(message, start, end)` triples.
- `_BracketDepths` replaces the three copy-pasted depth walks in
  `_split_parameters`, `_before_top_level_assignment`, and
  `_top_level_contains`, preserving each caller's tolerance for stray
  closers. The two single-bracket matchers stay separate on purpose; folding
  a forward brace scan and a backward paren scan into one generic helper
  would cost more readability than it saves.
- Confidence values are named once at module scope; the zero-or-one
  `tag_matches` loop became a plain conditional.

Verification: full suite green, plus an A/B dump of symbols, relationships,
and diagnostics for all 37 fixture C/header files against the pre-change
parser: byte-identical output.

## Phase 3: split the storage adapter

Status: complete (2026-08-22)

Findings addressed: 5.

Landed as:

- `serialization.diagnostic_to_dict` now owns the diagnostic payload format,
  next to its reader `diagnostic_from_dict`; `_replace_diagnostics` in
  `sqlite.py` uses it. Payload bytes are unchanged (`sort_keys=True`, same
  key set), so rows written by earlier versions stay readable.
- `list_diagnostics` (prefix match) and `_load_diagnostics` (exact match) now
  delegate to one `_read_diagnostics(connection, repository_id,
  exact_context=..., context_prefix=...)` builder with a shared row-to-model
  conversion.
- The missing blank line between `get_repository` and
  `list_repository_files` is fixed. Method order was assessed and already
  groups by aggregate; no reshuffle needed.

One slip during this phase (a return statement accidentally nested inside
`if row is None`) was caught immediately by the existing storage tests rather
than by review.

## Phase 4: decompose the Make adapter

Status: complete (2026-08-22)

Findings addressed: 4 (_build_result, parse_output), 6 (4-tuple).

Landed as:

- `ParsedMakeOutput` replaces the anonymous four-collection tuple returned by
  `parse_output`.
- `parse_output` keeps only logical-line classification (entering/leaving/
  make-message/command); `_process_command_line` handles shell splitting,
  `cd` tracking, and token dispatch; `_record_invocation` holds forced-include
  checks, missing-source diagnostics, and compilation-unit construction.
- `_build_result` now orchestrates four focused pieces: parsing,
  `_execution_diagnostics` (CI-BUILD-001/002, CI-COMP-001),
  `_compiler_versions`, and `_capability_records`. The nested capability
  ternary chains became explicit conditionals with identical outcomes.

Verification: full suite green, plus an A/B dump over all six fixture dry-run
samples (linux, embedded, wrapper, missing-input, tests, recursive): commands,
invocations, units, capabilities, diagnostics, and fingerprints byte-identical
against the pre-change adapter.

## Phase 5: CLI dispatch and dead-code removal

Status: complete (2026-08-22)

Findings addressed: 8 (vestigial code), 11 (stale wording), plus the
composition typing note.

Landed as:

- `cli/main.py` dispatches through a `_HANDLERS` map to per-command functions
  (`_run_init`, `_run_doctor`, `_run_scan`, `_run_recovery`, `_run_build`,
  `_run_build_discover`); argparse setup and every exit-code rule are
  unchanged.
- Deleted unused `AnalysisResult` and `JsonValue` from domain models along
  with the now-unused `typing.Any` import.
- `Application.storage_factory` is typed as
  `Callable[[Path], SQLiteAnalysisStorage]` instead of the bare class,
  matching what services accept.
- The scanner's stale "not implemented until Phase 3" capability reason now
  states that membership comes from build discovery runs while scanning only
  records build inputs. `repository.md` explicitly labels its build-awareness
  section as scan-scoped and points readers at `cintel build discover`
  instead of implying build state is always absent. Covered by
  `test_markdown_labels_build_awareness_as_scan_scoped`.
- `list_build_configurations` stays as a declared port seam, noted as
  reserved in the roadmap's architecture table.

## Documentation and script sync checklist (per phase)

Status: current through Phase 5. This file, the roadmap's verification
baseline, and the roadmap audit-findings notes were updated after each phase.
`README.md` needed no change: no user-facing commands or outputs changed.
`scripts/install.py` and `.portfolio/architecture.md` were untouched because
packaging and the composition architecture did not change.

## Definition of done for the cleanup effort

All six phases landed, suite green throughout, fixture untouched, docs synced.
The codebase then reads the way its architecture diagram claims: one identity
helper, one exclusion matcher, parsers and adapters split by job, storage
serialization in one module, and no dead models.
