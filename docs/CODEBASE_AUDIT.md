# Codebase audit: maintainability findings

- Audit date: 2026-08-22
- Audited revision: `945fca5` (`main`)
- Scope: all of `src/cintel`, `scripts/`, `tests/` (excluding the fixture repository, see below)
- Method: full read of every module under `src/cintel`, test-to-interface coverage mapping, baseline run of the test suite
- Latest re-audit: 2026-10-10, post Phase 6; see "Audit 2026-10-10" at the end of this file

Out of scope and untouchable: `tests/fixtures/complex_c_project`. That tree is
cintel's own test subject. Its expected findings, Makefiles, generated inputs,
and validator scripts exist to exercise the tool end to end. Refactors must not
modify it.

## What already holds up

The ports-and-adapters split is real. The domain imports nothing from
adapters, application, or the CLI; only
`adapters/commands/subprocess_runner.py` imports `subprocess`; the composition
root builds everything per invocation with no global instances. Structured
diagnostics flow from the deepest adapters out to CLI output without turning
into strings along the way. This is worth saying up front because the findings
below are about size and duplication inside an architecture that is basically
sound.

Baseline: 64 tests pass (50 unit, 14 integration) via
`PYTHONPATH=src python3 -m unittest discover -s tests`.

## Findings

### 1. Repository identity is derived five different ways

The same conceptual value, "the id for this repository root", is computed in
five places with two different resolve idioms:

- `application/scanning.py:39` uses
  `stable_id("repository", str(root.resolve(strict=False)))` where `root` is
  `Path(config.repository_root)` with no `expanduser()`.
- `application/initialization.py:42,84` uses `expanduser().resolve()` first.
- `application/build_discovery.py:44,56` uses `.resolve()` after
  `expanduser()` happens upstream.
- `application/build_discovery.py:165-167` recomputes it a second time inside
  the same service.
- `application/recovery.py:188-190` recomputes it again.

Through the normal CLI path these agree today because the config loader
expands and resolves before anything else runs. But the invariant lives in
five places, one of which skips `expanduser()` and uses
`resolve(strict=False)` while the rest do not. Construct an `AppConfig`
directly (as tests and future embedders do) with a literal `~/repo` path and
`scan` will persist state under a different repository id than `init`,
`build discover`, and `resume` did. Nothing warns; data just splits across two
ids in the same database. One helper in `utilities.paths`, called everywhere,
removes the whole class of failure.

### 2. Exclusion matching exists twice and has already drifted

- `adapters/repositories/filesystem.py:211-218` `_is_excluded` matches the
  file name, the full relative posix value, and every individual path part,
  and the scanner re-checks every file against exclusions.
- `application/doctor.py:266-271` `_excluded` matches only name and full
  value, and `_detect_inputs` applies it only when pruning directories during
  its walk, never per file.

So doctor's detected-inputs report can count files that `scan` would exclude,
and the two functions answer pattern questions differently for part-style
patterns. The consequence today is limited to doctor's detection counts, but
this is exactly how scan and doctor drift apart over time. One shared matcher
in utilities should serve both callers.

### 3. Fixture-specific logic sits in the production recovery path

`application/recovery.py:284-286` replaces the literal `<FIXTURE_ROOT>` with
the configured repository root when reading imported artifacts. This makes the
fixture's saved dry-run files portable, which is fine as a capability, but
nothing in `InputArtifact`, the artifact port, or any user-facing doc declares
that placeholder substitution is a feature. A real user's artifact containing
that string gets silently rewritten. Either document the placeholder as a
supported template or move the substitution into the artifact provider under a
name that says what it does.

### 4. Oversized methods that each do three or more jobs

- `ConservativeCSourceParser.parse` (`adapters/parsing/conservative.py:97-301`,
  roughly 205 lines): scope/fingerprint setup, kind gating, file reading,
  masking, directive parsing, construct dispatch, symbol assembly, dedup. It
  constructs `SourceAnalysisResult` three times with 14 identical keyword
  arguments each time (`conservative.py:119-133`, `145-159`, `287-301`).
- `MakeBuildDiscovery._build_result` (`adapters/build/make.py:64-249`):
  diagnostic assembly, compiler-version probing, fingerprinting, capability
  synthesis, source-file existence classification, result construction. The
  nested conditional expressions picking capability statuses at `make.py:163-169`
  and `186-193` require backtracking to parse.
- `MakeBuildDiscovery.parse_output` (`make.py:291-469`): four nested loops
  (logical line, shell segment, parsed invocation, forced include) sharing
  mutable lists, returning four parallel collections as an anonymous tuple.
- `SQLiteAnalysisStorage.save_build_discovery` (`sqlite.py:242-353`): five
  tables written inline with delete-plus-reinsert repeated per table.
- `cli.main.main` (`cli/main.py:75-188`): string-dispatch chain where the
  error-exit-code rule is spelled inline at four separate sites
  (`main.py:93`, `99-105`, `122`, `165-171`).

### 5. The storage adapter is one class doing ten aggregates' work

`SQLiteAnalysisStorage` (`sqlite.py:49-648`) implements the entire
`AnalysisStorage` port: repositories, files, diagnostics, capabilities,
reports, build configurations, discovery runs, invocations, units, commands,
artifacts, workflow state, and source analysis. Serialization is split
inconsistently between `serialization.py` and this file:

- The diagnostic write path builds payloads by hand inside
  `_replace_diagnostics` (`sqlite.py:687-731`) while the read side delegates
  to `diagnostic_from_dict` (`serialization.py:185`). Writer and reader for
  the same format live in different modules.
- Two nearly identical loaders, `list_diagnostics` (`sqlite.py:395-410`) and
  `_load_diagnostics` (`sqlite.py:734-749`), differ only in exact versus
  prefix context matching.
- Most rows store extracted columns plus a full JSON payload of the same
  object, and readers merge them back with `data.update(...)`
  (`sqlite.py:406-409`). Every row carries two representations that must stay
  in sync.
- Formatting slip: no blank line between `get_repository` and
  `list_repository_files` (`sqlite.py:108-109`), which is what unreviewed
  hand-edited SQL files look like.

### 6. Anonymous tuples as return contracts

- `_top_level_constructs` returns a tuple of `(message, start, end)` triples
  nested in another tuple (`conservative.py:440-495`); call sites unpack
  positionally.
- `parse_output` returns commands, invocations, units, and diagnostics as one
  anonymous 4-tuple (`make.py:291-298`).
- `GuidedRecoveryService._stored_evidence` returns units, diagnostics, and
  artifacts positionally (`recovery.py:231-249`).

Each is fine until someone adds a field. With no type checker configured, a
new element shifts every unpack silently. Small frozen dataclasses would make
these signatures self-describing.

### 7. Triplicated depth-scanning logic in the parser

`_split_parameters` (`conservative.py:563-584`),
`_before_top_level_assignment` (`849-859`), and `_top_level_contains`
(`862-872`) each re-implement the same bracket-depth walk with the same depths
and pairs dicts, alongside separate `_matching_brace` (`498-507`) and
`_matching_open_parenthesis` (`551-560`) scanners. One small scanner helper
covers all five uses.

### 8. Vestigial code

- `conservative.py:675-683`: `tag_matches` is either empty or holds exactly
  one match, then a loop iterates it. Write the conditional directly.
- `domain/models.py:503`: `JsonValue` alias is used nowhere.
- `domain/models.py:380-385`: `AnalysisResult` dataclass is unused;
  `RecoveryResult` fills the workflow-result role.
- `ports/storage.py:54` and `sqlite.py:364`: `list_build_configurations` has
  no caller in application, CLI, or tests.
- `pyproject.toml:24-25`: `[tool.unittest]` is not a key any tool reads.
- `composition.py:36`: `Application.storage_factory` is typed as the concrete
  `type[SQLiteAnalysisStorage]` while every service accepts a callable
  factory; the composition dataclass leaks the adapter type it exists to hide.

### 9. Repeated micro-boilerplate

- Storage lifecycle (`factory -> initialize -> try -> finally close`) appears
  in `scanning.py:46-94`, `build_discovery.py:58-69`, `104-114`, `123-133`,
  `168-175`, and `initialization.py:89-97`, while `recovery.py:222-229`
  already wraps the same thing in a private contextmanager nobody shares.
- Confidence magic numbers (0.8, 0.85, 0.9) scattered through
  `conservative.py:406`, `614`, `701`, `751`, `835`.
- The CLI error exit rule repeated four times (see finding 4).

### 10. No lint, format, or type checking anywhere

`pyproject.toml` configures packaging only. Finding 5's missing blank line is
the kind of slip a formatter prevents; finding 6's positional unpacking is the
kind mypy catches. Dev-only tooling would not break the zero-runtime-dependency
promise, but adding it is a decision for the maintainer, not a prerequisite for
the refactors below.

### 11. Stale wording confirmed still present

The roadmap audit section already lists these; both verified still true at
this revision: `filesystem.py:185` claims build discovery "is not implemented
until Phase 3", and `reports/repository.py:69-76` always tells readers build
awareness is unavailable regardless of persisted discoveries.

## Test coverage assessment

Adapter-level unit coverage is good and integration coverage exercises real
CLI flows. Interfaces with direct tests:

| Interface | Tests |
|---|---|
| `FileSystemRepositoryDiscovery` | `tests/unit/test_repository_discovery.py` |
| `mask_c_non_code`, `ConservativeCSourceParser` | `tests/unit/test_conservative_parser.py` |
| `GCCCompilerCommandParser` | `tests/unit/test_compiler_arguments.py` |
| `MakeBuildDiscovery` (adapter, fake runner) | `tests/unit/test_make_discovery.py` |
| `SQLiteAnalysisStorage`, v1 migration, newer-schema rejection | `tests/unit/test_storage.py` |
| config load/render | `tests/unit/test_configuration.py` |
| `SubprocessCommandRunner` capture/file/missing-executable | `tests/unit/test_command_runner.py` |
| artifact validation, secrets, hashing, guidance, diagnostics policy | respective unit files |
| `InitializationService` | `tests/integration/test_initialization.py` |
| `BuildDiscoveryService`, `RepositoryScanService` wiring | `tests/integration/test_build_discovery.py` |
| CLI surface, guided recovery, fixture validators | `tests/integration/test_cli.py`, `tests/integration/test_complex_fixture.py` |

Gaps to close before refactoring begins are listed as Phase 0 targets in
`docs/REFACTOR_PLAN.md`.

## Audit 2026-10-10: post-Phase 6 re-audit

- Audited revision: `0c300de` (`main`)
- Scope: all of `src/cintel`, `scripts/`, `tests/`; the fixture repository
  stays out of scope and untouched
- Method: read every module, mapped tests to interfaces, measured function
  sizes with an AST scan, traced CLI paths for out-of-order commands, ran the
  suite
- Baseline: 200 tests (168 unit, 32 integration), all passing in under three
  seconds

### What still holds up

The architecture survived Phase 6 without erosion. One module imports
`subprocess`. The domain imports nothing outward. Composition builds every
dependency per invocation. The earlier refactor's consolidations held: one
repository-id helper, one exclusion matcher, one storage lifecycle context
manager.

### Confirmed bugs

1. `cintel analyze` on a misspelled repository path raises an uncaught
   `sqlite3.IntegrityError` (`FOREIGN KEY constraint failed`) and creates
   `.code-intelligence/index.sqlite` under the typo path.
   `application/analysis.py:100` discards the scan result's diagnostics, the
   missing-root path at `application/scanning.py:46-50` supplies the only
   error, and the workflow-state write then references a repository row that
   was never stored. `doctor` and `report` fail correctly, so behavior is
   inconsistent across commands.
2. A nonexistent function name prints
   `Ambiguous function name: foo (0 definitions)`. `_select_definition` at
   `application/queries.py:320-342` returns `None` for zero definitions and for
   several, and the renderer at `cli/presentation.py:256-262` assumes
   ambiguity. It affects `show function`, `callers`, `callees`, and
   `context function`, and the message hides the "run analyze first" case.
3. `build units` with nothing discovered exits 0, while `build show` and
   `symbols` exit 1 for empty results.
4. `context function foo --budget 0` raises `ValueError` at
   `application/context.py:75-76` and prints a traceback; `cli/main.py:163`
   catches only `CintelError`.
5. `build discover --input-file` ignores `--input-type` and always passes
   `make_dry_run` (`cli/main.py:245-252`).
6. `setup --input-file X` silently runs the resume path and
   `instructions --input-file X` silently ignores the flag
   (`cli/main.py:192-206`).
7. Global options must come before the subcommand, and no help text or README
   line says so. `cintel doctor --repository .` fails with
   `unrecognized arguments`.
8. `--build-config` defaults to `"default"` invisibly. After
   `build discover --build-config debug`, plain `cintel analyze` falls back to
   file-scoped analysis and plain `cintel build units` lists nothing, with no
   hint (`cli/main.py:55`, `215-223`, `230-233`).
9. Outside a TTY, `make -n` runs with no preview and no `$(shell ...)` warning,
   because the interactive branch requires `sys.stdin.isatty()`
   (`cli/main.py:259-276`). `README.md:296-300` promises a preview and
   confirmation.
10. Nine options have no help text. `--verbose` affects only `build discover`.
    Text renderers drop diagnostic `suggested_actions`, so scan, build,
    analysis, and report errors carry no next steps
    (`cli/presentation.py:90-94`, `120-123`, `178-181`, `317-320`).
11. `start.sh` dies on a bad repository path at the unguarded `cd` (line 112),
    exits the whole script when Make discovery fails (lines 198-202), and
    swallows analyze and report failures (lines 241 and 246) while still
    printing "Done".
12. `cintel scan --output-directory <unwritable>` raises an uncaught
    `PermissionError` from `SQLiteAnalysisStorage.initialize`
    (`adapters/storage/sqlite.py:63`) before any diagnostic can be produced.
    `doctor` reports the same condition correctly as a structured error.

Status update 2026-10-10: all twelve findings above are fixed in Phase 2 of
`docs/IMPROVEMENT_PLAN.md`, each with a regression test.

### Complexity

`MarkdownReportRenderer` is 791 lines and `SQLiteAnalysisStorage` is 777.
Both were split by job in earlier phases but never by size.
`SourceAnalysisService.analyze` is 113 lines and `_capabilities` is 58.
`queries.py` repeats the function-definition filter in `function()` and
`_definitions`. The parser and Make adapter stay as they are; earlier
decomposition made them readable, and further splitting would be churn.

Status update 2026-10-10: Phase 3 split both classes into packages, moved
`_capabilities` into `application/analysis_capabilities.py`, and deduplicated
the query filter. Renderer output and storage tables were verified unchanged
against pre-change snapshots. The parser and Make adapter are untouched, as
planned.

### Agent navigation

48 of 62 modules have no module docstring. `src/cintel` contains 11 comments
total. Ports define every contract without documentation. There is no
`AGENTS.md` and no test enforcing import direction. `.portfolio/architecture.md`
still says cross-file resolution "is not yet exposed through the CLI".

Status update 2026-10-10: Phase 4 added `AGENTS.md`, module docstrings
everywhere, contract-level docstrings for ports, services, storage, and the
CLI, and a documentation ratchet test. The stale architecture line is fixed in
Phase 5.

### Test coverage

Adapter and happy-path coverage is strong. The gaps are failure paths:
corrupt or too-new SQLite, CLI exit-code contracts for error diagnostics,
`build show`, seven of twelve presentation renderers, artifact and guidance
error branches, output-directory permission failures, and out-of-order
`report`, `symbols`, and `context`. The committed `coverage.xml` is stale; it
predates Phase 6.

### Documentation drift

`README.md:131-144` calls the fixture future work and `README.md:310-316`
calls guided recovery planned, both implemented long ago.
`docs/CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md:481-495` still lists README
reconciliation as pending and claims report and context workflows are pending,
which Phase 6 finished.

### Tooling landed with this audit

`pyproject.toml` now configures ruff (rules `E4`, `E7`, `E9`, `F`, `I`, `UP`,
`B`, `SIM`, with `tests/fixtures` excluded) and mypy (`check_untyped_defs`,
`warn_unused_ignores`, `warn_redundant_casts`, `no_implicit_optional`, over
`src/cintel`). The first run fixed 147 mechanical findings and a set of real
annotation bugs: undefined report-entry names in
`adapters/reports/repository.py`, a shadowed loop variable there, an
overly-broad `dict[str, object]` return in `application/queries.py`, missing
symbol narrowing in queries and reports, and untyped relationship reads in
`adapters/storage/serialization.py`, which now has `Literal` overloads. Ruff
and mypy are clean and all 200 tests pass. `ruff format` is not adopted yet;
86 files would change, and that mechanical diff deserves its own phase.
