# Codebase audit: maintainability findings

- Audit date: 2026-08-22
- Audited revision: `945fca5` (`main`)
- Scope: all of `src/cintel`, `scripts/`, `tests/` (excluding the fixture repository, see below)
- Method: full read of every module under `src/cintel`, test-to-interface coverage mapping, baseline run of the test suite

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
