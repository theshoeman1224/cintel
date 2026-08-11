# Legacy C Code Intelligence: Current Capabilities and MVP Roadmap

- Audit date: 2026-08-10
- Audited base revision: `83294e9` (`main`)
- Implemented vertical slices: Phases 1–4 and Phase 5A foundation
- Recommended next vertical slice: Phase 5B, source-analysis workflow and resolution

## Executive summary

The repository currently provides a tested, offline, build-aware foundation for
legacy C analysis. It can initialize a local workspace, inspect the available
toolchain, inventory C and Make inputs, evaluate or import GNU Make dry-run
output, normalize GCC-style compilation commands, persist the results in
SQLite, and guide a user through supplying missing build evidence.

Phase 5A adds a conservative parser that extracts includes, macros, function
definitions and declarations, basic named types, typedefs, and file-scope
variables. Schema version 5 stores those symbols, include relationships,
parser diagnostics, and per-file or per-compilation-unit analysis state.

The next phase should implement the source-analysis application workflow,
cross-file linking, and direct-call extraction. Phase 6 can then turn that index into the
developer-facing symbol, relationship, and context reports required for the
MVP. Optional GCC enrichment remains Phase 7.

## Verification baseline

The following checks were run during this audit:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m cintel --help
PYTHONPATH=src python3 -m cintel build --help
```

Result:

- 62 tests passed.
- The suite contains 50 unit tests and 12 integration tests.
- The CLI exposes `init`, `doctor`, `scan`, `setup`, `instructions`, `resume`,
  and the `build discover`, `build units`, and `build show` subcommands.
- The complex C fixture verifies scanning, saved and live-style Make discovery,
  compiler argument handling, multiple build configurations, generated-input
  guidance, all six artifact validators, artifact staleness, and resumability.
- A parser smoke test processed all 37 C/header files in the complex fixture
  without crashing.
- The package has no runtime third-party dependencies.
- Only `src/cintel/adapters/commands/subprocess_runner.py` imports
  `subprocess`.

The tests require either an editable installation (`python -m pip install -e .`)
or `PYTHONPATH=src` when run directly from a fresh checkout.

## Architecture status

| Area | Status | Current implementation |
|---|---|---|
| Domain models | Implemented for current and planned MVP concepts | Immutable dataclasses and enums cover repositories, files, builds, compiler invocations, symbols, relationships, capabilities, diagnostics, artifacts, workflow state, commands, and context packages. |
| Application services | Implemented for Phases 1–4 | Initialization, doctor, scanning, Make discovery, and guided recovery are orchestrated outside the CLI. |
| Ports | Implemented | Protocols exist for command execution, build discovery, compiler behavior, source parsing, storage, report rendering, guidance, artifacts, and AI. |
| Command adapter | Implemented | Standard-library subprocess execution uses argument lists, `shell=False`, explicit working directories, environment overrides, timeout, output destination, and risk metadata. |
| Make adapter | Implemented | GNU Make command creation, dry-run capture/import, directory tracking, command splitting, and compiler-command discovery are isolated here. |
| Compiler adapters | Partially implemented | GCC-style argument parsing and compiler version lookup exist. General GCC capability probing and enrichment do not. |
| Repository adapter | Implemented | Filesystem discovery, exclusions, hashing, metadata, and incremental hash reuse exist. |
| Source parser adapter | Phase 5A implemented | The conservative parser implements offset-preserving masking and basic extraction behind `SourceParser`; application orchestration and cross-file resolution remain. |
| SQLite adapter | Implemented through Phase 5A | Schema version 5 adds source-analysis runs, symbols, relationships, and context-scoped parser diagnostics to the Phase 1–4 state. |
| Report adapters | Partially implemented | Markdown and JSON repository inventory plus Markdown recovery instructions exist. Build, symbol, graph, diagnostics, capability, and context report families are incomplete. |
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
    files/
    folders/
    graphs/
    reports/
        repository.json
    symbols/
```

Some directories are reserved for later phases. At present:

- `repository.md` is the primary human-readable repository inventory;
- `REQUIRED_INPUTS.md` is the human-readable recovery guide;
- `reports/repository.json` is the machine-readable inventory;
- build discovery and unit views are rendered through CLI output; and
- `index.sqlite` contains durable Phase 1–5A state, including parser results.

## Diagnostics currently implemented

The codebase currently emits stable codes in these families:

- `CI-REPO-001` through `CI-REPO-004`;
- `CI-BUILD-001` through `CI-BUILD-005`;
- `CI-COMP-001` and `CI-COMP-002`; and
- `CI-INPUT-001` through `CI-INPUT-003`; and
- `CI-PARSE-001`.

The domain diagnostic includes severity, message, technical details, missing
capability, recoverability, suggested actions, related paths, related commands,
and metadata.

Report-generation diagnostics such as `CI-GEN-001` remain to be introduced.

## Known gaps and current limitations

### Functional gaps

- No source-analysis workflow or `cintel analyze` command exists.
- Parser results are not yet populated through an application service or CLI.
- Includes are extracted but unresolved; direct calls are not extracted.
- Declaration-to-definition, type-usage, and global-usage relationships are
  not built.
- Entry-point reachability and direct-recursion cycle analysis do not exist.
- `cintel symbols`, `show function`, `callers`, `callees`,
  `context function`, and `report` do not exist.
- There are no Markdown/JSON build-unit, function, include, call,
  diagnostics, capability, graph, or context reports.
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

- The repository scanner currently emits a stale capability reason saying Make
  discovery is not implemented until Phase 3. Phase 3 is implemented.
- `repository.md` is scan-scoped and always says build awareness is unavailable
  until Make discovery; it does not consult persisted build discoveries.
- Parts of the README still describe the implemented guided-recovery commands
  and complex fixture as planned future work.
- The direct-from-checkout test command in the README assumes an editable
  installation; without one it needs `PYTHONPATH=src`.
- `CompilerProvider` remains an architectural seam rather than a complete
  enrichment provider; `SourceParser` now has a Phase 5A adapter.
- SQLite now stores source symbols and relationships, but query/report
  workflows are not wired to the CLI.

These are documentation/report integration issues or later-phase gaps; they do
not invalidate the passing Phase 1–5A test baseline.

## Recommended next phase: Phase 5B, Analysis workflow and resolution

### Phase boundary

Phase 5B should orchestrate the Phase 5A parser and persistence foundation over
scanned files and discovered compilation units. It should add deterministic
cross-file relationships and incremental reuse, while leaving rich reports and
context packaging for Phase 6.

### Proposed implementation

1. Add a source-analysis application service that selects repository files and
   build-aware compilation units without embedding parser logic.
2. Add `cintel analyze` as the Phase 5 workflow entry point.
3. Wire the parser and service in the composition root.
4. Extract conservative direct-call candidates from function bodies.
5. Resolve same-file static targets before unique external definitions and
   retain ambiguous targets as unresolved.
6. Link declarations to definitions without collapsing file-scoped symbols.
7. Resolve include relationships using source directories and compilation-unit
   include paths where possible.
8. Add practical type/global usage relationships, entry-point reachability,
   and direct-recursion cycle detection.
9. Reuse analysis by source hash, compilation-unit fingerprint, and parser
   version so changed inputs invalidate only dependent results.
10. Keep analysis useful without Make by creating file-scoped,
    reduced-capability analysis records.

### Phase 5B acceptance criteria

Phase 5B should not be considered complete until:

- all Phase 1–5A tests continue to pass;
- configured and unconfigured analysis workflows are integration-tested;
- declaration-to-definition and direct-call resolution is deterministic;
- recursive direct-call cycles and entry-point reachability are calculated;
- unchanged analysis is reused and source or compiler-argument changes mark
  dependent results stale;
- analysis succeeds in reduced mode without Make or GCC; and
- the complex fixture verifies its mandatory function, direct-call, include,
  type, macro, and global findings while classifying callback and
  macro-generated behavior as uncertain.

## Work remaining to create the MVP

### Phase 5B: Source-analysis workflow and relationships

Required:

- direct calls;
- declaration/definition linking;
- include resolution plus call, practical type-use, and global-use relationships;
- entry-point reachability;
- recursive direct-call cycles;
- configuration membership;
- incremental/resumable source analysis.

### Phase 6: Reports, queries, and context

Required:

- `cintel symbols`;
- `cintel show function <name>`;
- `cintel callers <name>`;
- `cintel callees <name>`;
- `cintel context function <name> [--budget N]`;
- `cintel report`;
- disambiguation for duplicate function names;
- deterministic context prioritization and character budgeting;
- function definition and declaration excerpts;
- compiler defines and include paths in context;
- callers, callees, types, globals, macros, comments, and relevant headers;
- capability, confidence, and provenance notes;
- repository inventory integrated with persisted build state;
- selected-build and excluded-source reports;
- compilation-unit report;
- function, include, caller/callee, diagnostics, and capability indexes;
- Markdown and JSON output through report-renderer adapters; and
- report metadata and `CI-GEN-001` failures.

Phase 6 should also fix the stale scan-only build-awareness wording identified
by this audit.

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
