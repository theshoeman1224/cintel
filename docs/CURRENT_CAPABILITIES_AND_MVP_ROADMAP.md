# Legacy C Code Intelligence: Current Capabilities and MVP Roadmap

- Audit date: 2026-08-10, re-verified 2026-08-30
- Audited base revision: `83294e9` (`main`); Phase 5B landed on `main`
- Implemented vertical slices: Phases 1–4, Phase 5A foundation, the
  Phase 5B source-analysis workflow and resolution, and Phase 6
  (query commands, function context packages, report families)
- Recommended next vertical slice: Phase 7, optional GCC enrichment
  (the deterministic MVP is otherwise complete)

## Executive summary

The repository currently provides a tested, offline, build-aware foundation for
legacy C analysis. It can initialize a local workspace, inspect the available
toolchain, inventory C and Make inputs, evaluate or import GNU Make dry-run
output, normalize GCC-style compilation commands, persist the results in
SQLite, and guide a user through supplying missing build evidence.

Phase 5A adds a conservative parser that extracts includes, macros, function
definitions and declarations, basic named types, typedefs, file-scope
variables, direct-call candidates from function bodies, and same-file
variable usages. Schema version 6 stores those symbols, include relationships,
parser diagnostics, and per-file or per-compilation-unit analysis state, with
denormalized query-projection columns added for Phase 6 symbol and
call-graph queries.

Phase 5B adds `cintel analyze`: an application service that parses scanned
files and build-aware compilation units with incremental reuse by source
hash, compilation-unit fingerprint, and parser version. It resolves direct
calls deterministically (same-file static definitions first, then a single
repository-wide definition, restricted to build-member files for
build-configured callers; ambiguous targets stay unresolved), resolves
includes against source directories and compilation-unit `-I` paths, and
derives entry-point reachability plus direct-recursion cycles from the call
graph.

Phase 6 turns that index into developer-facing output: schema v6 adds
query-projection columns, the query commands (`symbols`, `show function`,
`callers`, `callees`) answer symbol and relationship questions with
deterministic disambiguation, `cintel context function` builds a budgeted
context package per function, and `cintel report` generates every Markdown
and JSON report family — including a build-state-integrated repository
inventory — through the report-renderer adapters with `CI-GEN-001` failure
diagnostics. The complex fixture's validator now enforces mandatory analysis
findings against the new JSON reports. Optional GCC enrichment remains
Phase 7; final MVP hardening follows it.

## Verification baseline

The following checks were run during this audit:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m cintel --help
PYTHONPATH=src python3 -m cintel build --help
```

Result (re-verified 2026-08-30 after Phase 6):

- 177 tests passed: 145 unit and 32 integration, including the live complex
  fixture build, the cleanup-effort safety nets, the analysis workflow tests,
  and the new Phase 6 query, context, report, and migration suites.
- New Phase 6 suites cover schema v6 migrations with projection backfill from
  v2/v3/v4/v5 snapshots, the storage query methods, the symbol query service
  (disambiguation, callers/callees, deduplication), the context service
  (budgeting, truncation, determinism), every report family in both formats,
  the integrated inventory build state, and end-to-end CLI behavior with
  exit-code contracts.
- The cleanup unified repository-id derivation and exclusion matching (doctor
  now skips excluded files exactly as scan does), consolidated the storage
  lifecycle and diagnostic serialization, decomposed the parser, Make
  adapter, and CLI dispatch, and removed dead models. Parser and Make-discovery
  outputs were verified byte-identical against pre-refactor dumps over every
  fixture sample.
- The CLI exposes `init`, `doctor`, `scan`, `setup`, `instructions`, `resume`,
  `analyze`, the `build discover`, `build units`, and `build show` subcommands,
  and the Phase 6 commands `symbols`, `show function`, `callers`, `callees`,
  `context function`, and `report`.
- The complex C fixture verifies scanning, saved and live-style Make discovery,
  compiler argument handling, multiple build configurations, generated-input
  guidance, all six artifact validators, artifact staleness, resumability, and
  mandatory analysis findings validated against the Phase 6 JSON reports
  (28 passed, 0 missing, 4 heuristic, 2 unsupported by design).
- A parser smoke test processed all 37 C/header files in the complex fixture
  without crashing.
- The package has no runtime third-party dependencies.
- Only `src/cintel/adapters/commands/subprocess_runner.py` imports
  `subprocess`.

The tests require either an editable installation (`python scripts/install.py`)
or `PYTHONPATH=src` when run directly from a fresh checkout.

## Architecture status

| Area | Status | Current implementation |
|---|---|---|
| Domain models | Implemented for current and planned MVP concepts | Immutable dataclasses and enums cover repositories, files, builds, compiler invocations, symbols, relationships, capabilities, diagnostics, artifacts, workflow state, commands, and context packages. |
| Application services | Implemented for Phases 1–5B | Initialization, doctor, scanning, Make discovery, guided recovery, and source analysis are orchestrated outside the CLI. |
| Ports | Implemented | Protocols exist for command execution, build discovery, compiler behavior, source parsing, storage, report rendering, guidance, artifacts, and AI. |
| Command adapter | Implemented | Standard-library subprocess execution uses argument lists, `shell=False`, explicit working directories, environment overrides, timeout, output destination, and risk metadata. |
| Make adapter | Implemented | GNU Make command creation, dry-run capture/import, directory tracking, command splitting, and compiler-command discovery are isolated here. |
| Compiler adapters | Partially implemented | GCC-style argument parsing and compiler version lookup exist. General GCC capability probing and enrichment do not. |
| Repository adapter | Implemented | Filesystem discovery, exclusions, hashing, metadata, and incremental hash reuse exist. |
| Source parser adapter | Phase 5A/5B implemented | The conservative parser implements offset-preserving masking plus symbol, call-candidate, and variable-usage extraction behind `SourceParser`; `SourceAnalysisService` orchestrates it with incremental reuse and deterministic resolution. |
| SQLite adapter | Implemented through Phase 5A | Schema version 6 keeps the Phase 1–5 state plus source-analysis runs, symbols, and relationships, and adds denormalized query-projection columns (repository/file identity, definition flags, caller/callee ids and spellings) with matching indexes so Phase 6 queries run in SQL. Migrations backfill the projections from stored payloads. `list_build_configurations` remains a reserved port surface until Phase 6 query workflows need it. |
| Report adapters | Implemented | Markdown and JSON renderers cover the repository inventory (with persisted build state), build selection, compilation units, function index, call graph, include index, diagnostics index, capability index, and the Markdown recovery guidance. All families dispatch on report name and reject unsupported names. |
| AI adapter | Implemented as disabled | The deterministic core does not depend on AI. Requests to generate AI content fail explicitly. |
| Composition root | Implemented | Dependencies are constructed in `composition.py`; there are no global service instances. |

## Current user-facing capabilities

### Workspace initialization and configuration

`cintel init <repository>`:

- creates `.code-intelligence/` or an explicitly selected output directory;
- writes a simple TOML configuration;
- initializes the SQLite database;
- creates the planned output subdirectories;
- is idempotent; and
- refuses to overwrite a user-modified configuration.

Configuration supports the repository root, output directory, database path,
scan exclusions, and disabled-by-default AI setting. Python 3.11's `tomllib`
is used for reading, with no TOML-writing dependency.

### Environment diagnostics

`cintel doctor` inspects:

- Python version;
- Make, GCC, `cc`, and executable cross-GCC candidates;
- `nm`, `objdump`, `readelf`, `find`, and `grep`;
- optional Graphviz `dot`;
- output-directory writability;
- Makefiles and `.mk` fragments;
- build logs;
- dependency files;
- object files; and
- `compile_commands.json`.

Results use structured diagnostics and capability records rather than plain
error strings. Missing Make or GCC degrades available capabilities without
preventing repository scanning.

### Repository scanning

`cintel scan`:

- recursively discovers `.c`, `.h`, Makefiles, and `.mk` files;
- applies configurable exclusions;
- excludes `.git`, `.code-intelligence`, and common build/object directories by
  default;
- records relative path, absolute path, kind, byte size, modification time, and
  SHA-256 hash;
- skips source symlinks conservatively;
- reuses hashes when stored size and modification time show a file is unchanged;
- continues after individual file failures with diagnostics;
- persists the inventory in SQLite; and
- writes human-readable Markdown and structured JSON repository inventories.

Scanning works without Git, Make, GCC, Clang, Docker, or a database server.

### GNU Make build discovery

`cintel build discover` supports:

- repository root;
- Makefile;
- Make working directory;
- target;
- repeated `NAME=value` Make variables;
- repeated environment overrides;
- named build configurations;
- forced rediscovery; and
- timestamp-respecting discovery by omitting `-B`.

The generated command is an argument list equivalent to:

```bash
make -n -B -f <makefile> <target> NAME=value
```

The adapter:

- preserves raw standard output, standard error, exit code, and duration;
- tracks recursive Make `Entering directory` and `Leaving directory` messages;
- handles `cd directory && command`;
- splits reasonably parseable `&&` and `;` command sequences;
- recognizes environment prefixes;
- recognizes `ccache`, `distcc`, `env`, `nice`, and `time` launchers;
- recognizes `cc`, GCC, cross-GCC, and Clang-like compiler names
  conservatively;
- retains non-compiler and unparseable commands;
- emits diagnostics for incomplete or malformed evidence; and
- works from a validated saved dry-run when Make is unavailable.

Interactive terminal use previews the Make evaluation and warns about
`$(shell ...)`. The CLI does not run real builds or unknown generation targets.

### Compiler-command normalization

For each discovered compile command, the GCC-style parser records:

- compiler executable and launcher/wrapper tokens;
- source and object paths;
- effective working directory;
- original command and raw arguments;
- `-I` and `-isystem` paths;
- `-D` definitions and values;
- `-U` undefinitions;
- `-include` forced includes;
- `-std` language standard;
- optimization, debug, warning, architecture, and dependency flags; and
- every remaining unclassified argument.

Paths preserve the original spelling, normalized absolute path, and
repository-relative path when possible. Stable compilation-unit identifiers and
fingerprints allow one source file to occur in multiple build configurations.
The current implementation also records compiler version information when a
read-only version probe succeeds.

### Build membership and caching

Build discovery:

- maps discovered source paths to scanned repository files;
- records selected source files;
- records repository source files excluded from the selected build;
- reports build-referenced source or forced-include files that are absent;
- classifies missing files as possible generated inputs;
- stores configurations, commands, invocations, units, and discovery runs;
- computes an input fingerprint from build inputs and selection parameters;
- computes a build fingerprint from normalized commands and available compiler
  versions; and
- reuses a matching cached discovery unless forced.

`cintel build units` lists persisted compilation units, and
`cintel build show <source-file>` filters them by source and optional build
configuration.

### Symbol, call-graph, and relationship queries

Phase 6 adds read-only queries over the stored analysis index (schema v6
query-projection columns):

- `cintel symbols [--kind function|variable|type|macro] [name]` lists stored
  symbols with kind, location, definition/declaration state, linkage, and a
  kind-specific detail (signature, type spelling, or macro replacement);
- `cintel show function <name> [--file <relative-path>]` presents the
  definition, its declarations, direct callers with call-site locations, and
  direct callees with definition locations;
- `cintel callers <name>` and `cintel callees <name>` list the same resolved
  and unresolved direct-call edges on their own;
- duplicate function names list their candidate definitions and exit with
  status 1; `--file` selects one definition deterministically;
- empty results exit with status 1; `--json` renders every query as
  machine-readable output.

Because symbol ids embed the compilation-unit scope, the same definition can
be stored once per build configuration; queries collapse those duplicates by
source location, so every symbol is presented once.

### Function context packages

`cintel context function <name> [--budget N] [--file <relative-path>]`
builds a deterministic, budgeted `ContextPackage` for one function and
writes it under `context/<name>__<path-slug>.md` in the output directory:

- sections fill in a fixed priority order: definition excerpt, declarations,
  preceding comment block, callers, callees, globals used, local types, file
  macros, relevant headers (includes of the defining file plus declaration
  locations), compiler defines and include paths for the unit, and
  capability/confidence/provenance notes;
- the default budget is 8000 characters; the first section that does not fit
  ends the package, only the definition excerpt may be truncated (with an
  explicit marker), and an `Omitted sections` note records what was dropped;
- packages carry `character_budget` and `used_characters` plus a
  deterministic-context capability record;
- generated files are recorded in the generated-reports metadata under the
  `function_context:<filename>` report name; and
- ambiguous names behave like the query commands: candidates are listed and
  the command exits with status 1.

### Reports

`cintel report` regenerates every report family from persisted state in
both Markdown and JSON through the report-renderer adapters. The
repository inventory (`repository.md`, `reports/repository.json`) is
refreshed incrementally by the scan service and now integrates persisted
build state — configuration names, compilation-unit counts, and files with
analysis results — replacing the former scan-only build-awareness
disclaimer (the stale wording flagged by this audit is fixed).

Families written under `reports/` (each with `GeneratedReportMetadata`
per format):

- `build_selection` — selected sources and excluded C sources per
  configuration;
- `compilation_units` — units with configuration, source, compiler,
  fingerprint, define, and include-path counts;
- `function_index` — deduplicated functions with definition/declaration
  state, linkage, and location, plus definition and declaration counts;
- `call_graph` — deduplicated direct-call edges with caller, call-site
  line, callee definition, and resolution, plus an unresolved count;
- `include_index` — include directives with resolved targets and an
  unresolved count;
- `diagnostics_index` and `capability_index` — every diagnostic and
  capability record.

Failures render as `CI-GEN-001` (report generation failed) diagnostics with
reduced-capability recoverability; a failing family never aborts the
remaining ones. Except for the timestamped inventory, identical stored
state produces byte-identical reports. Report generation records a
`report` workflow state.

### Guided input and recovery

`cintel setup`, `cintel instructions`, and `cintel resume` provide the Phase 4
recovery workflow:

- missing capabilities are represented by diagnostics;
- exact command instructions include reason, working directory, output file,
  risk, validation steps, warnings, and resume command;
- instructions are written to `REQUIRED_INPUTS.md`;
- suggested commands are not executed automatically;
- user evidence is copied under the configured `input/` directory;
- imported content is hashed and validated before use;
- provenance, build configuration, validation, and staleness are persisted;
- workflow stages are persisted and resumed; and
- repository scanning continues when build evidence is unavailable.

The six accepted artifact types are:

- Make dry-run output;
- verbose build log;
- source-oriented file list;
- dependency file;
- preprocessed C source; and
- macro listing.

Only validated Make dry-run output is currently consumed by a downstream
analysis workflow. The other artifact types are validated and retained for
future source or compiler enrichment.

### Security and offline behavior

Current safeguards include:

- no network dependency for deterministic analysis;
- no source transmission;
- disabled AI integration;
- no `shell=True`;
- subprocess access isolated to one adapter;
- no automatic environment dump;
- likely secret assignment values redacted from command provenance and
  guidance;
- explicit warnings for Make evaluation, builds, environment logs,
  preprocessed source, and future AI sharing;
- no automatic real build or generation target; and
- generated output kept under `.code-intelligence/` unless explicitly
  overridden.

## Persisted and generated outputs

The current implementation creates or uses:

```text
.code-intelligence/
    config.toml
    index.sqlite
    repository.md
    REQUIRED_INPUTS.md
    input/
    cache/
    context/
        <function>__<path-slug>.md
    files/
    folders/
    graphs/
    reports/
        repository.json
        build_selection.{md,json}
        compilation_units.{md,json}
        function_index.{md,json}
        symbol_index.{md,json}
        call_graph.{md,json}
        include_index.{md,json}
        global_usage.{md,json}
        diagnostics_index.{md,json}
        capability_index.{md,json}
    symbols/
```

Some directories are reserved for later phases. At present:

- `repository.md` is the primary human-readable repository inventory;
- `REQUIRED_INPUTS.md` is the human-readable recovery guide;
- `reports/repository.json` is the machine-readable inventory;
- `context/` holds deterministic function context packages written by
  `cintel context function`;
- `reports/` holds the Phase 6 Markdown/JSON report families alongside
  `reports/repository.json`; and
- `index.sqlite` contains durable Phase 1–6 state, including parser results,
  query-projection columns, and generated-report metadata.

## Diagnostics currently implemented

The codebase currently emits stable codes in these families:

- `CI-REPO-001` through `CI-REPO-004`;
- `CI-BUILD-001` through `CI-BUILD-005`;
- `CI-COMP-001` and `CI-COMP-002`; and
- `CI-INPUT-001` through `CI-INPUT-003`; and
- `CI-PARSE-001`; and
- `CI-ANLZ-001`; and
- `CI-GEN-001`.

All identifiers are defined once as the `DiagnosticCode` enumeration in
`cintel.domain.diagnostics`; the string values are the public contract.
Command classifications (`compiler`, `directory_change`, `unparsed`,
`recursive_make`, `other`) are likewise defined as `CommandClassification`,
and workflow stages (including the Phase 6 `report` stage) as
`WorkflowStage`, both in `cintel.domain.models`.

The domain diagnostic includes severity, message, technical details, missing
capability, recoverability, suggested actions, related paths, related commands,
and metadata.

`CI-GEN-001` reports a failed report-family generation with
reduced-capability recoverability; generation of the remaining families
continues.

## Known gaps and current limitations

### Functional gaps

- Symbol/relationship query commands, deterministic function context
  packages, and all report families including `cintel report` exist;
  remaining Phase 6 work is the complex-fixture analysis-finding validation
  and documentation reconciliation.
- Call resolution is monotonic by design: an already-resolved call keeps its
  original target even when a later analysis pass introduces a competing
  definition; re-running `analyze --force-analysis` after sources change
  recomputes resolution from scratch.
- Includes resolve against source directories and unit `-I` paths; system
  headers and absent generated headers stay explicitly unresolved.
- Declaration-to-definition linkage manifests through resolved call targets;
  a dedicated declaration-link relationship kind does not exist.
- Type-usage relationships are not extracted (global variable usage is).
- Reachability is computed over direct calls only; indirect dispatch through
  function pointers remains uncertain by design.
- GCC dependency, preprocessing, macro, and dump capability probing is not
  implemented.
- Validated build logs, file lists, dependency files, preprocessed files, and
  macro listings are retained but not yet ingested into analysis.

### Accuracy boundaries

The conservative parser does not claim complete C semantic correctness.
Function pointers, runtime dispatch, macro-generated code, conditional
compilation, compiler extensions, implementations in headers, generated code,
weak symbols, assembly, link-time selection, and incomplete build environments
will remain explicit limitations.

### Audit findings to correct during subsequent work

Status update 2026-08-30: Phase 6 corrected the scan-only build-awareness
wording and integrated persisted build state into the repository inventory
(see below). The remaining items still stand.

- Corrected in Phase 6: `repository.md` no longer remains scan-scoped; the
  inventory now integrates persisted build discoveries, and the stale
  scan-only build-awareness wording was replaced.
- Parts of the README still describe the implemented guided-recovery commands
  and complex fixture as planned future work.
- The direct-from-checkout test command in the README assumes an editable
  installation; without one it needs `PYTHONPATH=src`.
- `CompilerProvider` remains an architectural seam rather than a complete
  enrichment provider; `SourceParser` now has a Phase 5A adapter.
- SQLite stores source symbols and relationships; Phase 6 query commands are
  wired to the CLI, while report/context workflows are still pending.

These are documentation/report integration issues or later-phase gaps; they do
not invalidate the passing Phase 1–5A test baseline.

## Recommended next phase: Phase 6, Reports, queries, and context

### Phase boundary

Phase 5B is implemented: `cintel analyze` orchestrates the Phase 5A parser
and persistence foundation over scanned files and discovered compilation
units, resolves cross-file relationships deterministically, and reuses
analysis incrementally. Phase 6 turns that stored index into developer-facing
output; context packaging and rich report families belong there.

### What Phase 5B delivered against its plan

1. `SourceAnalysisService` selects repository files and build-aware
   compilation units without embedding parser logic.
2. `cintel analyze` is the Phase 5 workflow entry point (`--build-config`,
   `--force-analysis`, `--json`).
3. The parser and service are wired in the composition root.
4. The parser extracts conservative direct-call candidates from function
   bodies (control keywords and member-access dispatch excluded) plus
   same-file variable usages.
5. Calls resolve to a same-file static definition first, then to a single
   repository-wide definition; ambiguous targets stay unresolved. For
   build-configured callers, repository-wide candidates are restricted to
   definitions in files that are members of the selected build, so excluded
   per-platform sources cannot shadow the in-build definition.
6. Declaration-to-definition linkage manifests through resolved call targets;
   file-scoped symbols are never collapsed.
7. Includes resolve using the including file's directory and compilation-unit
   `-I` paths where possible.
8. Entry-point reachability and direct-recursion cycles derive from the
   resolved call graph; global-usage relationships cover same-file variables
   (type usage remains future work).
9. Analysis reuse keys on source hash, compilation-unit fingerprint, and
   parser version; changed inputs reparse only their own results.
10. Without Make evidence, every file is analyzed file-scoped so analysis
    stays useful in reduced mode.

Integration tests cover configured and unconfigured runs, incremental reuse,
and forced reanalysis on the repository fixtures.

## Work remaining to create the MVP

### Phase 5B: Source-analysis workflow and relationships

Implemented (see above).

### Phase 6: Reports, queries, and context

Implemented (see above). Delivered against the plan:

- `cintel symbols`, `show function <name>`, `callers <name>`, `callees <name>`;
- `cintel context function <name> [--budget N]` with deterministic
  prioritization, character budgeting, definition/declaration excerpts,
  compiler defines and include paths, callers, callees, globals, types,
  macros, relevant headers, and capability/confidence/provenance notes;
- `cintel report` regenerating every family in Markdown and JSON through the
  report-renderer adapters, with per-format `GeneratedReportMetadata` and
  `CI-GEN-001` failure diagnostics;
- disambiguation for duplicate function names (candidate listing plus
  `--file` selection, exit status 1);
- the repository inventory integrated with persisted build state, fixing the
  stale scan-only build-awareness wording; and
- the complex fixture validator now enforces mandatory analysis findings
  against the `symbol_index`, `call_graph`, `include_index`, and
  `global_usage` JSON reports.

The `symbol_index` and `global_usage` report families extend the planned
index list so the fixture's machine-readable expectations (globals, types,
macros, global reads/writes) are fully validated.

### Phase 7: Optional GCC enrichment

Optional for the deterministic core, but planned for the complete staged MVP:

- robust GCC and cross-GCC detection;
- compiler capability records;
- dependency generation with `-M` and `-MM`;
- preprocessed source generation with `-E`;
- predefined and active macro collection with `-dM` and `-dD`;
- safe probing of `-fdump-ipa-cgraph`, `-fdump-tree-original`,
  `-fdump-tree-gimple`, and `-fdump-tree-cfg`;
- ingestion of dependency, preprocessing, macro, and supported dump artifacts;
- fake-runner and saved-output tests; and
- graceful fallback on absent or older GCC versions.

GCC dumps must remain optional. The MVP must continue to produce useful
repository and conservative source analysis without GCC.

### Final MVP hardening

After Phases 5–7:

- reconcile README examples and capability wording with actual behavior;
- run the complete complex fixture across Linux, embedded, tests, wrapper, and
  missing-input configurations;
- verify clean-checkout installation and the `cintel` console entry point on
  Python 3.11;
- verify all generated paths remain inside the configured output directory;
- audit secret redaction across new reports and artifacts;
- verify migrations from every supported schema version;
- verify interruption and resume at source-analysis and report stages;
- document which imported artifact types are consumed versus merely retained;
  and
- update the human and machine-readable fixture expectations for all supported
  findings.

## Definition of MVP completion

The MVP is complete when a user can point `cintel` at a C repository, scan it,
discover or import its Make build, analyze its C source conservatively, query
symbols and direct relationships, generate all required Markdown/JSON reports,
and create a deterministic budgeted function context package—while receiving
structured limitations and exact recovery guidance whenever the environment is
incomplete.

AI-generated summaries, C++, a GUI, complete function-pointer resolution, and
full compiler-grade C semantics remain explicitly out of scope.
