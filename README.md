# Legacy C Code Intelligence

Legacy C Code Intelligence (`cintel`) is an offline-first command-line
application for turning legacy C repositories into structured, build-aware
knowledge for developers and coding agents. The current codebase implements
the Phase 1 foundation and Phase 2 repository inventory: initialization,
environment diagnostics, recursive C/build-input discovery, incremental
SHA-256 hashing, GNU Make dry-run build discovery, compiler-command
normalization, SQLite state, deterministic Markdown/JSON inventory reports,
configuration, and dependency composition.

It does not send source code externally. AI is disabled by default, and the
deterministic analysis architecture does not depend on an AI model.

## Installation

Python 3.11 or newer is required. No runtime dependencies are required.

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cintel --help
```

Tests use the standard library:

```bash
python -m unittest discover -s tests -v
```

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
```

Generated state is kept under `.code-intelligence/`. `init` will not overwrite
a configuration whose contents differ from the configuration it would create.

## Example repository

A later phase will include a representative Make-based C fixture. Once
repository scanning and build discovery are implemented, the intended workflow
will resemble:

```bash
cintel --repository ./example scan
cintel --repository ./example --makefile Makefile --target all build discover
cintel --repository ./example analyze
cintel --repository ./example report
```

`scan` and the three `build` subcommands are implemented. Source analysis and
general reports in the example above are planned behavior and are deliberately
not exposed as successful no-ops.

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

Important: `make -n` can still evaluate `$(shell ...)` expressions. Future
interactive workflows preview Make evaluation commands and request
confirmation before running them. `--non-interactive` permits Makefile
evaluation but does not authorize mutating commands. Real builds and unknown
generation targets are never run automatically.

The parser follows recursive Make entering/leaving messages, `cd directory &&
command`, shell-aware `&&` and `;` boundaries, environment prefixes, `ccache`,
`distcc`, `env`, `nice`, and `time`. GCC, `cc`, cross-GCC names, and Clang-like
commands are recognized conservatively. Unknown compiler flags and raw commands
are preserved. A read-only `<compiler> --version` probe contributes available
compiler identity to the build fingerprint; broader GCC capability probing
remains optional future enrichment.

## Guided setup and offline behavior

The planned `setup`, `instructions`, and `resume` workflows will identify
missing evidence, explain why it matters, provide an exact command and working
directory, validate the resulting artifact, and resume from stored workflow
state. Reduced-capability repository analysis will remain available when Make,
GCC, generated headers, object files, or saved build logs are absent.

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
- `application` coordinates use cases such as initialization and doctor checks.
- `ports` defines command, build, compiler, parser, storage, rendering,
  guidance, and AI contracts.
- `adapters` contains filesystem repository discovery and output writing,
  Markdown/JSON repository rendering, Make discovery, GCC-style argument
  normalization, the subprocess command runner, SQLite persistence, and the
  disabled AI provider. Later adapters will add compiler enrichment and C
  parsing behavior.
- `configuration` reads TOML and owns the small initial configuration schema.
- `cli` parses arguments, invokes application services, and renders results.
- `composition.py` is the composition root; there are no global service
  instances.

The domain imports no process, SQLite, Make, GCC, CLI-library, or AI-SDK code.

### Adding adapters

To add a build-system adapter, implement `BuildDiscoveryProvider` and construct
it in the composition root. Build-specific parsing stays in that adapter.

To add a compiler adapter, implement `CompilerProvider`; capability probing and
compiler-specific flags must not leak into domain or application services.

To add a parser adapter, implement `SourceParser`. It must report confidence and
diagnostics rather than claiming unsupported semantic certainty.

To add a report format, implement `ReportRenderer` and keep serialization or
template details in its adapter.

Future AI integration will implement `AIProvider`. It is optional by design and
must not become a dependency of deterministic indexing or context selection.

## Configuration

Python 3.11's `tomllib` reads `.code-intelligence/config.toml`. Phase 1 writes a
small documented schema without adding a TOML dependency. Default exclusions
include `.git`, `.code-intelligence`, and common build/object directories.

SQLite stores a schema version in `schema_metadata`. Schema v2 adds repository
file inventory and generated-report metadata. Schema v3 adds build
configurations, discovery runs, raw build commands, compiler invocations, and
compilation units. Migrations are applied
incrementally by the storage adapter; a database newer than the application is
rejected explicitly.

## Known MVP limitations

The Phase 1 foundation, Phase 2 repository inventory, and Phase 3 Make build
discovery are implemented. Conservative C parsing, relationships, guided
artifact recovery, broader reports, context packages, and GCC enrichment
belong to subsequent vertical slices.

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
