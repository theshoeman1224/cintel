# Legacy C Code Intelligence

Legacy C Code Intelligence (`cintel`) is an offline-first command-line
application that turns legacy C repositories into a structured, build-aware
index for developers and coding agents. It initializes a local workspace,
inspects the toolchain, inventories C and Make inputs, evaluates or imports a
GNU Make build, normalizes compiler commands, analyzes C sources
conservatively, answers symbol and call-graph queries, builds budgeted
function context packages, and writes deterministic Markdown and JSON
reports.

It does not send source code externally. AI is disabled by default, and the
deterministic analysis architecture does not depend on an AI model.

## Installation

Python 3.11 or newer is required. No runtime dependencies are required.

### Quickest start

```bash
./start.sh
```

The script sets up the `.venv` virtual environment, installs the project,
optionally runs the test suite, then walks through a first analysis. It asks
for a repository path and offers three kinds of build evidence:

- a live Make dry-run (Makefile, target, build configuration name, and Make
  variables are prompted);
- an imported saved `make -n` transcript (input type, build configuration
  name, Makefile, and target are prompted). Only `make_dry_run` evidence
  enables build-aware analysis today; the other input types are validated and
  kept, and analysis falls back to file-scoped;
- none, for file-scoped analysis.

It then runs `init`, `doctor`, `scan`, `setup`, `build discover`/`resume`,
`analyze`, and `report`, and prints a findings summary pointing at
`REQUIRED_INPUTS.md` and the generated report families
(`reports/diagnostics_index.md`, `reports/include_index.md`,
`reports/call_graph.md`).

Accepting the default path (the built-in fixture) analyzes a disposable copy
at `.fixture-output/demo/complex_c_project`, with its generated inputs built
by `make generate` when Make is available, so the committed fixture is never
written to. An invalid path is rejected and the prompt repeats. The script is
safe to re-run; existing virtualenvs, the demo copy, workspaces, and analysis
state are reused.

### Manual installation

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python scripts/install.py
cintel --help
```

The installer compares the project version with the active environment and
skips `pip install -e .` when that version is already installed.

Tests use the standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

To run them under coverage and produce `coverage.xml` for SonarQube:

```bash
pip install -e '.[dev]'
PYTHONPATH=src coverage run -m unittest discover -s tests
coverage xml
```

Run `sonar-scanner` afterwards so the report is uploaded with the analysis.

The dev extra also installs `ruff` and `mypy`:

```bash
pip install -e '.[dev]'
ruff check src scripts tests
mypy
```

## Test fixtures

`scripts/fixtures.py` discovers, sets up, verifies, cleans, and runs the test
fixtures under `tests/fixtures/` by delegating to the scripts that already
exist in the repository (the installer, each fixture's own tools, and the
documented `cintel` CLI flow):

```bash
python scripts/fixtures.py list                      # fixtures, requirements, operations
python scripts/fixtures.py setup complex_c_project   # build generated fixture artifacts
python scripts/fixtures.py verify all                # fixture self-checks (on a temporary copy)
python scripts/fixtures.py clean all                 # remove generated artifacts
python scripts/fixtures.py run complex_c_project     # bootstrap, analyze, validate
```

`run` performs the same steps a user would (`init`, `doctor`, `scan`, `build
discover`, `analyze`, `report`) against a disposable copy of the fixture and
validates the repository, build, and analysis reports against
`expected_findings.json`; it fails if any mandatory finding goes unchecked. Committed fixture sources are
never modified. New fixtures are added by dropping a `fixture.py` into their
directory; see `tests/fixtures/README.md` for the contract.

### SonarCloud (PR analysis)

`.github/workflows/sonarcloud.yml` runs the test suite under coverage and
uploads the result to SonarCloud on every push to `main` and every pull
request. One-time setup required:

1. In SonarCloud, under **Administration > Analysis Method**, switch the
   project to **CI-based analysis** (automatic analysis must be disabled
   when CI-based analysis is active).
2. Generate a token under **My Account > Security** and add it as the
   `SONAR_TOKEN` repository secret in GitHub
   (**Settings > Secrets and variables > Actions**).

The workflow overrides `sonar.projectKey` and `sonar.organization` for
SonarCloud; the local `sonar-project.properties` keeps the project key used
by local `sonar-scanner` runs.

## Quick start

Initialize a repository-local workspace, then inspect the development
environment:

```bash
cintel init /path/to/legacy-c-repository
cintel --repository /path/to/legacy-c-repository doctor
cintel --repository /path/to/legacy-c-repository scan
cintel --repository /path/to/legacy-c-repository \
  --makefile Makefile --target all --build-config debug \
  --make-var MODE=debug --non-interactive build discover
cintel --repository /path/to/legacy-c-repository \
  --build-config debug build units
cintel --repository /path/to/legacy-c-repository \
  --makefile Makefile --target all --build-config debug setup
cintel --repository /path/to/legacy-c-repository \
  --makefile Makefile --target all --build-config debug \
  --input-file /path/to/make-dry-run.txt resume
cintel --repository /path/to/legacy-c-repository --build-config debug analyze
cintel --repository /path/to/legacy-c-repository show function main
cintel --repository /path/to/legacy-c-repository report
```

Global options such as `--repository`, `--config`, and `--build-config` must
appear before the subcommand. `--output-directory` moves the workspace
somewhere other than `<repository>/.code-intelligence/`.
`--make-working-directory` sets the directory Make runs in (default: the
repository root), and `--env NAME=value` (repeatable) adds an environment
override for the Make run. Generated state is kept under
`.code-intelligence/`. `init` will not overwrite a configuration whose
contents differ from the configuration it would create.

## Command reference

| Command | Purpose |
|---|---|
| `init [path]` | Create the workspace, configuration, and database |
| `doctor` | Inspect tools, inputs, and capabilities |
| `scan` | Inventory C sources, headers, and Make inputs |
| `setup` | Assess missing evidence and write REQUIRED_INPUTS.md |
| `instructions` | Regenerate REQUIRED_INPUTS.md |
| `resume` | Validate supplied evidence and resume the workflow |
| `analyze` | Parse sources and resolve relationships |
| `build discover` | Run or import a GNU Make dry-run |
| `build units` | List compilation units |
| `build show <source>` | Units for one source file |
| `symbols [name]` | List stored symbols |
| `show function <name>` | Definition, callers, and callees |
| `callers <name>` | Direct callers of a function |
| `callees <name>` | Direct callees of a function |
| `context function <name>` | Build a budgeted context package |
| `report` | Regenerate every report family |

## Exit codes and output

- `0`: success.
- `1`: the query ran but matched nothing, a function name was ambiguous or
  absent, or a read-only command found no workspace.
- `2`: an error, including configuration, storage, and validation failures.

Every command accepts `--json`. Errors render as a structured
`{"error": {...}}` object on standard output and keep the same exit codes.
Text output prints each distinct diagnostic once, with an occurrence count
when it repeats, the related paths (up to five), and `Action:` lines with
next steps when the diagnostic carries them.

The read-only commands (`symbols`, `show function`, `callers`, `callees`,
`context function`, `build units`, and `build show`) never create a
workspace. Without one they print the `cintel init` hint and exit 1; with
`--json` the hint is a `{"error": {"type": "WorkspaceNotFound", ...}}`
object.

`--verbose` prints, on standard error, which configuration was used
(`--config`, the repository's `.code-intelligence/config.toml`, or built-in
defaults) and how long the command took. Setting `enabled = true` under
`[ai]` has no effect: AI integration is not implemented. Every command warns
about it on standard error, and `doctor` reports `CI-CONF-001`.

## Example repository

`tests/fixtures/complex_c_project` is a representative Make-based C
repository with multiple build configurations, recursive Make, generated
inputs, wrapper commands, plugins, and saved dry-run evidence. It doubles as
the demo in `./start.sh` and as the tool's own end-to-end test subject.
`./start.sh` copies it for you; to run the flow by hand, copy it first so the
committed fixture stays untouched, and build its generated inputs in the copy
(without that step, build discovery warns about the missing generated files):

```bash
cp -r tests/fixtures/complex_c_project /tmp/cintel-demo
rm -rf /tmp/cintel-demo/.code-intelligence
make -s -C /tmp/cintel-demo generate CONFIG=linux
cintel init /tmp/cintel-demo
cintel --repository /tmp/cintel-demo doctor
cintel --repository /tmp/cintel-demo scan
cintel --repository /tmp/cintel-demo \
  --makefile Makefile --target linux --build-config linux --non-interactive build discover
cintel --repository /tmp/cintel-demo --build-config linux analyze
cintel --repository /tmp/cintel-demo report
```

## Symbol and relationship queries

After `analyze`, the stored index answers read-only queries. Queries and
reports read the scope of the latest `analyze` run: with `--build-config NAME`,
that configuration's compilation units plus file-scoped results for C files
outside the build; without it, file-scoped results only. Results from earlier
runs under other configurations stay stored but are not mixed in, so rerun
`analyze` with the configuration you want to inspect. Ambiguous
function names (several definitions) list their candidates and exit with
status 1; rerun with `--file <repository-relative-path>` to choose one.
Unknown names report that the index has no such definition and point at
`cintel analyze` when analysis has not run:

```bash
cintel --repository ./example symbols                       # every stored symbol
cintel --repository ./example symbols --kind function       # functions only
cintel --repository ./example symbols project_value         # exact name
cintel --repository ./example show function project_value   # definition, callers, callees, declarations
cintel --repository ./example show function helper --file src/util.c
cintel --repository ./example callers project_value
cintel --repository ./example callees main
```

`--json` renders every query as machine-readable output. Empty results exit
with status 1. Callers show the call site inside each calling function;
callees show the callee's definition location when the call resolved.

## Function context packages

`cintel context function <name> [--budget N] [--file <path>]` builds a
deterministic, budgeted context package for one function and writes it under
`.code-intelligence/context/<name>__<path-slug>.md`:

- sections are filled in a fixed priority order — definition excerpt,
  declarations, preceding comment, callers, callees, globals used, local
  types, file macros, relevant headers, compiler defines and include paths,
  and capability/provenance notes;
- the first section that does not fit the character budget (default 8000)
  ends the package; the definition excerpt alone may be truncated, and an
  `Omitted sections` note lists whatever was dropped;
- the same stored state and budget always produce the same file content;
- the CLI prints the written path, budget usage, and section list.

```bash
cintel --repository ./example context function project_value
cintel --repository ./example context function helper --budget 4000 --file src/util.c
```

## Reports

`cintel report` regenerates every report family from persisted state —
Markdown and JSON side by side under `.code-intelligence/reports/` (the
repository inventory stays at its conventional locations):

- `repository.md` and `reports/repository.json` — repository inventory
  integrated with persisted build state (configurations, unit counts,
  analyzed files);
- `reports/build_selection.{md,json}` — selected sources and excluded
  C sources per build configuration;
- `reports/compilation_units.{md,json}` — units with configuration, source,
  compiler, define, and include-path counts;
- `reports/function_index.{md,json}` — every analyzed function with
  definition/declaration state, linkage, and location;
- `reports/symbol_index.{md,json}` — every stored function, variable,
  type, and macro with definition state, linkage, and location;
- `reports/call_graph.{md,json}` — deduplicated direct-call edges with
  call-site lines, callee definitions, and explicit unresolved edges;
- `reports/include_index.{md,json}` — include directives with resolved
  targets;
- `reports/global_usage.{md,json}` — each function's references to
  global variables, with where the function and the variable live;
- `reports/diagnostics_index.{md,json}` and
  `reports/capability_index.{md,json}` — every diagnostic and capability
  record with provenance classification.

Every Markdown report opens with a **What this report means** section and
a **Value meanings** glossary for its columns and domain values
(`confirmed_direct`/`unresolved`, `internal`/`external` linkage, severity
levels, and so on), so the artifacts are readable without prior
knowledge of the schema.

Every written file is recorded in the generated-reports metadata (name,
format, path, SHA-256). Failures are reported as `CI-GEN-001` diagnostics
and never abort the remaining families. Apart from the timestamped
inventory, the same stored state always produces byte-identical reports.

```bash
cintel --repository ./example report
```

## Source analysis

`cintel analyze` runs the conservative parser over scanned C sources and
headers, then resolves relationships deterministically:

- direct-call candidates extracted from function bodies resolve to a
  same-file static definition first, then to a single repository-wide
  definition; ambiguous targets stay explicitly unresolved;
- includes resolve against the including file's directory plus the selected
  build configuration's `-I` paths;
- entry-point reachability and direct-recursion cycles derive from the
  resolved call graph;
- unchanged files are reused by source hash, compilation-unit fingerprint,
  and parser version; `--force-analysis` reparses everything.

Without a build configuration, every file is analyzed file-scoped, so
analysis works when Make evidence is unavailable.

The summary reports both sides of each relationship count: `Calls: N resolved,
M unresolved` and `Includes: N resolved, M unresolved`. System headers, absent
generated headers, and macros the conservative parser cannot verify appear as
unresolved by design; `reports/include_index.md` lists every unresolved target.

## Guided recovery and saved inputs

`cintel setup` scans the repository and writes
`.code-intelligence/REQUIRED_INPUTS.md` without executing the suggested commands.
`cintel instructions` regenerates that report from persisted diagnostics.
`cintel resume` validates an optional `--input-file`, records its SHA-256 hash and
provenance, checks it for later staleness, and continues from completed stages.
`setup` and `instructions` reject `--input-file`; use `resume` to import evidence.

Imported Make dry-run text may contain path placeholders for paths that differ
on the machine where it will be analyzed. `--path-placeholder OLD=NEW`
(repeatable) replaces each OLD token with NEW before parsing;
`<FIXTURE_ROOT>` maps to the configured repository root by default.

Supported `--input-type` values are `make_dry_run`, `build_log`, `file_list`,
`dependency_file`, `preprocessed_source`, and `macro_listing`. A validated saved
Make dry-run is parsed through the same adapter as live Make output and can also
be supplied to `cintel build discover --input-file ...`.

Invalid artifacts receive `CI-INPUT-002`; modified or configuration-mismatched
artifacts receive `CI-INPUT-003`. Repository scanning remains usable when build
evidence is unavailable. Imported evidence is copied beneath the configured
`input/` directory. Command provenance redacts likely secret variables.

Generated guidance warns that Make evaluation can execute `$(shell ...)`, real
builds can modify files, environment/build logs can expose secrets, preprocessed
source can contain proprietary code and absolute paths, and future AI providers
must not receive source without explicit approval.

## Makefile discovery

The Make adapter asks GNU Make to evaluate the selected build using
an argument-list equivalent of:

```bash
make -n -B -f Makefile target VAR=value
```

Use `--respect-make-timestamps` to omit `-B`. Use
`--force-build-discovery` to bypass a matching cached result. Raw standard
output, standard error, normalized commands, non-compiler commands, and
unparseable command evidence are retained in SQLite.

`cintel` does not attempt to parse all Make syntax itself. Makefiles are
programs: includes, functions, recursive invocations, variable expansion and
`$(shell ...)` behavior cannot be reproduced reliably by a small parser.
Using Make preserves the build's actual evaluation semantics while the adapter
captures and conservatively interprets its output.

Important: `make -n` can still evaluate `$(shell ...)` expressions. Every
`build discover` run prints the evaluation command and the `$(shell ...)`
warning to standard error; an interactive terminal also asks for
confirmation first. `--non-interactive` permits Makefile evaluation but does
not authorize mutating commands. Real builds and unknown generation targets
are never run automatically.

The parser follows recursive Make entering/leaving messages, `cd directory &&
command`, shell-aware `&&` and `;` boundaries, environment prefixes, `ccache`,
`distcc`, `env`, `nice`, and `time`. GCC, `cc`, cross-GCC names, and Clang-like
commands are recognized conservatively. Unknown compiler flags and raw commands
are preserved. A read-only `<compiler> --version` probe contributes available
compiler identity to the build fingerprint; broader GCC capability probing
remains optional future enrichment.

## Offline behavior

All deterministic analysis is local and offline. SQLite is embedded through
Python's `sqlite3` module; no database server, Docker daemon, root privilege, or
Clang installation is required.

## Security

- Source code is not transmitted externally.
- AI providers are disabled, and future providers must require explicit source
  sharing approval.
- Commands use argument lists and `shell=False`.
- Only the command-runner adapter invokes subprocesses.
- Environment dumps are not captured automatically; they may contain secrets.
- Preprocessed files can contain proprietary source and absolute paths.
- Generated output defaults to `.code-intelligence/`; source files are never
  overwritten.
- Real builds and unknown generation targets are not automatically executed.

## Architecture

The project uses ports and adapters:

- `domain` contains immutable models, relationships, evidence, capabilities,
  and structured diagnostics.
- `application` coordinates the use cases: initialization, doctor, scanning,
  build discovery, guided recovery, source analysis, symbol queries, context
  packages, and reports.
- `ports` defines command, build, compiler, parser, storage, rendering,
  guidance, and AI contracts.
- `adapters` contains filesystem repository discovery and output writing,
  Markdown/JSON repository rendering, Make discovery, GCC-style argument
  normalization, conservative C parsing, the subprocess command runner, SQLite
  persistence, and the disabled AI provider. Later adapters will add compiler
  enrichment.
- `configuration` reads TOML and owns the small initial configuration schema.
- `cli` parses arguments, invokes application services, and renders results.
- `composition.py` is the composition root; there are no global service
  instances.

The domain imports no process, SQLite, Make, GCC, CLI-library, or AI-SDK code.

### Adding adapters

To add a build-system adapter, implement `BuildDiscoveryProvider` and construct
it in the composition root. Build-specific parsing stays in that adapter.

To add a compiler adapter, implement `CompilerCommandParser` (turns a compiler
command into a normalized invocation) and, for identity probing,
`CompilerMetadataProvider`. Capability probing and compiler-specific flags must
not leak into domain or application services. `CompilerProvider` is a reserved
port for future GCC enrichment; nothing implements or consumes it yet.

To add a parser adapter, implement `SourceParser`. It must report confidence and
diagnostics rather than claiming unsupported semantic certainty.

To add a report format, implement `ReportRenderer` and keep serialization or
template details in its adapter.

`AIProvider` is likewise reserved: only the disabled provider implements it,
and no service calls it. Future AI integration is optional by design and must
not become a dependency of deterministic indexing or context selection.

## Configuration

Python 3.11's `tomllib` reads `.code-intelligence/config.toml`. Phase 1 writes a
small documented schema without adding a TOML dependency. Default exclusions
include `.git`, `.code-intelligence`, `.venv`/`venv`, and common
build/object directories.

SQLite stores a schema version in `schema_metadata`. Schema v2 adds repository
file inventory and generated-report metadata. Schema v3 adds build
configurations, discovery runs, raw build commands, compiler invocations, and
compilation units. Schema v4 adds validated input artifacts and resumable
workflow state. Schema v5 adds per-file/configuration source-analysis state,
symbols, and relationships while parser diagnostics reuse context-scoped
diagnostic storage. Schema v6 adds query-projection columns for the symbol and
call-graph queries. Migrations are applied incrementally by the storage
adapter; a database newer than the application is rejected explicitly.

## Known MVP limitations

The Phase 1 foundation, Phase 2 repository inventory, Phase 3 Make build
discovery, Phase 4 guided recovery, the Phase 5A conservative
parser/persistence foundation, the Phase 5B source-analysis workflow
(`cintel analyze`), and all Phase 6 query commands, function context
packages, and report families are implemented. Optional GCC enrichment
belongs to the final vertical slice.

Even after those slices, conservative analysis will have known limitations:

- function pointers and runtime dispatch cannot generally be resolved;
- macros can generate code that lexical parsing cannot see accurately;
- conditional compilation depends on complete build flags and generated input;
- compiler extensions may be unsupported or only partially represented;
- headers may contain implementations and configuration-dependent definitions;
- generated code may be absent or stale;
- weak symbols and link-time selection require linker evidence;
- assembly is outside the C-only scope;
- link-time optimization and whole-program behavior may differ from source;
- incomplete build environments reduce include and semantic accuracy.

The tool will surface these as capabilities, evidence levels, confidence, and
structured diagnostics instead of silently inventing facts.
