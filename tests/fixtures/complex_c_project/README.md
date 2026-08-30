# Complex legacy C integration fixture

This deterministic fixture models a small sensor-processing and message-routing system.
It exists to exercise repository inventory, GNU Make discovery, compiler flags, source
analysis, symbol/call-graph reporting, diagnostics, graceful degradation, and
context-package selection.

## Layout

- `src/app` contains the production entry point.
- `src/configuration`, `src/core`, `src/drivers`, and `src/routing` contain application logic.
- `src/platform` provides common, Linux, and embedded-simulation implementations.
- `src/plugins` is built through recursive Make with environment-prefixed commands.
- `src/shared`, `src/telemetry`, and `src/include_cycle` exercise shared and conditional code.
- `src/legacy` is scanned but excluded from all selected builds.
- `third_party` is compiled through an `-isystem` include path.
- `generated` is produced from `templates` using a standard-library Python script.
- `unsupported` contains non-built assembly outside the C MVP.
- `expected` contains the versioned manifest, human expectations, and portable dry-runs.

## Make targets

- `make linux` builds the optimized Linux application with telemetry.
- `make embedded` builds the host-GCC embedded simulation without telemetry.
- `make tests` builds the framework-free test executable without production `main.c`.
- `make run-tests` builds and executes the tests.
- `make generate` writes the generated header and source for `CONFIG`.
- `make clean` removes build and generated outputs.
- `make print-config` prints the active configuration.
- `make missing-input-demo` intentionally compiles with a nonexistent forced include.

Normal verification:

```bash
make clean
make generate CONFIG=linux
make linux
make embedded
make run-tests
python3 tools/verify_fixture.py
```

The missing-input target is intentionally incomplete and is never executed by normal
verification. Its dry-run exists to exercise missing-generated-input guidance.

## Make discovery cases

The top-level Makefile includes five required `.mk` files and optionally includes
`local.mk`. Pattern rules compile most files. Plugin compilation uses recursive Make and
`env FIXTURE_MODULE=plugins gcc ...`. Quiet mode is the default; use `V=1` for verbose
recipes. Enable the POSIX-shell compiler wrapper with:

```bash
make linux USE_COMPILER_WRAPPER=1
```

Representative dry-runs:

```bash
make -n -B linux V=1
make -n -B embedded V=1
make -n -B tests V=1
make -n -B linux V=1 USE_COMPILER_WRAPPER=1
make -n -B missing-input-demo V=1
```

`tools/verify_fixture.py` regenerates saved outputs under `expected/sample_inputs/` and
normalizes the fixture root to `<FIXTURE_ROOT>`.

The same directory contains validated Phase 4 recovery examples: a verbose build log,
source-oriented file list, dependency file, preprocessed C source, and macro listing.
These allow every supported input-artifact validator to run without a network or a
complete external build environment.

## Generated files

`tools/generate_build_files.py` reads the two templates and creates
`generated/build_config.h` and `generated/version_info.c`. Values include platform,
configuration, feature switches, version, and a deterministic build identifier. The
header is passed with `-include`; the source is a normal compilation unit.

## CINTEL expectations

Important constructs carry adjacent comments of the form:

```c
/* CINTEL_EXPECT[DIRECT_CALL]: caller=application_initialize; callee=configuration_load */
```

Confirmed direct calls, build membership, compiler arguments, and file inventory are
deterministic. Callback dispatch, macro-generated functions, include-cycle semantics,
and weak-symbol behavior are intentionally ambiguous or compiler/linker dependent.

## Running cintel

From the project repository root:

```bash
PYTHONPATH=src python3 -m cintel \
  --repository tests/fixtures/complex_c_project \
  --output-directory /tmp/cintel-complex-fixture scan

PYTHONPATH=src python3 -m cintel \
  --repository tests/fixtures/complex_c_project \
  --output-directory /tmp/cintel-complex-fixture \
  --makefile Makefile --target linux --build-config linux \
  --non-interactive --force-build-discovery build discover
```

The current implementation exports repository JSON at
`/tmp/cintel-complex-fixture/reports/repository.json` and build JSON to standard output.
The main integration test runs `analyze --build-config linux` and `report`, then combines
the repository report, build report, and the Phase 6 analysis report families
(`symbol_index`, `call_graph`, `include_index`, `global_usage`) as `analysis_report`:

```json
{
  "repository_report": {},
  "build_report": {},
  "analysis_report": {
    "symbol_index": {"entries": []},
    "call_graph": {"edges": []},
    "include_index": {"entries": []},
    "global_usage": {"entries": []}
  }
}
```

Validate that envelope with:

```bash
python3 tests/fixtures/complex_c_project/tools/validate_cintel_results.py \
  --expected tests/fixtures/complex_c_project/expected/expected_findings.json \
  --actual /tmp/cintel-complex-fixture/actual.json \
  --configuration linux
```

The validator reports unsupported current-phase source findings separately from missing
supported findings; it does not silently turn unsupported capabilities into passes.
Required symbols must appear in the `symbol_index` report (by name, kind, and path);
required calls must appear as resolved `confirmed_direct` edges in the `call_graph`
report; required includes must match the `include_index` report; and required global
reads/writes must match the `global_usage` report (the conservative parser records the
usage without read/write direction). Heuristic findings — macro-generated symbols, weak
symbols, possible indirect calls, and include cycles — remain in the skipped-heuristic
bucket by design.

## Guided recovery

Generate safe recovery instructions without executing Make:

```bash
PYTHONPATH=src python3 -m cintel --repository tests/fixtures/complex_c_project \
  --output-directory /tmp/cintel-complex-fixture --makefile Makefile \
  --target linux --build-config linux setup
```

Import saved dry-run output and resume build discovery:

```bash
PYTHONPATH=src python3 -m cintel --repository tests/fixtures/complex_c_project \
  --output-directory /tmp/cintel-complex-fixture --makefile Makefile \
  --target linux --build-config linux \
  --input-file tests/fixtures/complex_c_project/expected/sample_inputs/make-linux-dry-run.txt \
  resume
```

Imported evidence is copied under the configured `input/` directory, SHA-256 hashed,
validated, persisted in SQLite, and checked for later modification. Invalid or stale
evidence is reported with `CI-INPUT-002` or `CI-INPUT-003`; repository scanning remains
available when build-aware analysis cannot resume.
