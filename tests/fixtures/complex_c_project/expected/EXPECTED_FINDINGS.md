# Expected findings

This document distinguishes deterministic MVP expectations from findings that require
future source intelligence. The machine-readable source of truth is
`expected_findings.json`.

## 1. Repository discovery

The inventory must find all `.c` and `.h` files, the top-level and plugin Makefiles,
and the five included `.mk` fragments. `src/legacy/unused_legacy_module.c` must be in
the repository inventory even though it is absent from every selected build.
Assembly inventory is currently unsupported by the C-only scanner and must be reported
as such rather than treated as a passing C finding.

## 2. Build discovery

Linux, embedded, and tests are distinct build configurations. Recursive Make enters
`src/plugins`, commands use an environment prefix there, and the same checksum source
has distinct compilation-unit identities. These are mandatory current-MVP findings.

## 3. Compiler flags

All configurations use C11, debug information, warnings, PIC, dependency generation,
project includes, a system vendor include, and the generated forced include. Linux uses
`-O2` and 32-bit checksum behavior; embedded uses `-O0` and 16-bit behavior; tests use
`-O1` and `UNIT_TEST`. Define, undefine, include-path, forced-include, and unknown-flag
preservation are deterministic current-MVP expectations.

## 4. Functions

Mandatory future source findings include `main`, `application_initialize`,
`application_run`, `router_classify_message`, and the static recursive
`perform_retry_sequence`. Macro-generated plugin handlers are heuristic.

## 5. Calls

The deterministic direct chain is `main -> application_initialize/application_run`,
then initialization calls configuration, platform, sensor, router, plugins, state
machine, and conditionally telemetry. Runtime execution calls sensor polling, routing,
and state processing. These are mandatory once direct-call extraction is implemented.

## 6. Includes

Project include relationships and the guarded `cycle_a.h`/`cycle_b.h` cycle are future
source-analysis expectations. The build-level include and system-include paths are
already mandatory and deterministic.

## 7. Types

Expected types include enums, nested structures, a union, bit fields, callback typedefs,
forward declarations, and the opaque `PlatformContext`. Type extraction is not exported
by the current phase.

## 8. Globals

`g_application_state` is externally declared and read/written by several functions.
`g_diagnostic_event_count` is volatile. Static state, a constant lookup table, a global
handler structure, and plugin registry data exercise storage and usage analysis.

## 9. Conditional compilation

Telemetry sources and calls exist only in Linux. Platform source membership changes
between Linux and embedded. Fast filtering and checksum width differ by configuration.

## 10. Generated inputs

`generated/build_config.h` and `generated/version_info.c` are standard-library-generated
inputs. The header is force-included and the source is compiled. The generated files are
mandatory when validation follows `make generate` or a normal build.

## 11. Ambiguous relationships

`router_dispatch` calls through `MessageHandler.handler`; that target is intentionally
possible/indirect. `DEFINE_PLUGIN_HANDLER` generates two functions. Both are heuristic
expectations and their absence must not be misreported as deterministic success.

## 12. Expected diagnostics

The non-default `missing-input-demo` target references
`generated/external_site_config.h`, which has no generator. The assembly source should
be classified outside the C MVP. These diagnostics apply only when the relevant target
or language inventory is requested.

## 13. Build-specific differences

Linux selects Linux platform and telemetry sources. Embedded selects the embedded host
simulation and excludes telemetry. Tests select Linux platform support, omit production
`main.c`, add three test sources, and define `UNIT_TEST`.

## 14. Known parser limitations

Function pointers, macro-generated functions, weak-symbol replacement, preprocessor
branch semantics, assembly, link-time behavior, and runtime dispatch are deliberately
represented without claims of complete semantic resolution.

## 15. Guided recovery

Phase 4 must produce a non-executing `REQUIRED_INPUTS.md`, validate all six saved
artifact types, import the saved Linux dry-run through the normal Make parser, preserve
artifact hashes and workflow stages in SQLite, reject empty input with `CI-INPUT-002`,
and detect later modification with `CI-INPUT-003`. Importing the
`missing-input-demo` dry-run must retain `CI-BUILD-005` and generate an exact read-only
`find` instruction for `generated/external_site_config.h`. Secret Make variables must
not appear in guidance or persisted command provenance.
