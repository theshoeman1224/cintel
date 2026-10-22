# AGENTS.md

Guidance for coding agents working in this repository. Keep it current when
architecture, commands, or invariants change.

## What this is

`cintel` is an offline-first CLI that turns legacy C repositories into a
build-aware index. No network calls, no runtime dependencies, no AI in the
deterministic path.

## Layout

```text
src/cintel/
  domain/          immutable models, diagnostics, errors; imports nothing outward
  ports/           protocol contracts; services depend on these, not adapters
  application/     use cases: init, doctor, scan, build, recovery, analyze, queries, context, reports
  adapters/        filesystem, GNU Make, GCC args, conservative parser, SQLite, Markdown/JSON, subprocess
  cli/             argparse, dispatch, exit codes, text/JSON rendering
  configuration/   TOML loading and the AppConfig model
  utilities/       hashing, paths, secrets
  composition.py   composition root; builds everything per invocation
tests/
  unit/            adapter and service tests
  integration/     CLI flows and the complex fixture driver
  fixtures/        test subjects; complex_c_project is untouchable
docs/              audit, improvement plan, roadmap
```

Import direction is enforced by `tests/unit/test_architecture.py`. Only
`adapters/commands/subprocess_runner.py` imports `subprocess`, and only
`adapters/storage/` imports `sqlite3`.

## Command flow

```text
init -> doctor -> scan -> build discover (or resume with evidence) -> analyze -> queries/context/report
```

- `scan` is safe to re-run; file hashes are reused when size and mtime match.
- `build discover` runs `make -n -B` or imports validated evidence, and caches on the input fingerprint.
- `analyze` reparses only changed targets, keyed on source hash, compilation-unit fingerprint, and parser version.
- `symbols`, `show function`, `callers`, `callees`, `context function`, and `report` read persisted state only, limited to the latest `analyze` run's scope (`application/analysis_scope.py`). `report` also re-scans to refresh the inventory.
- Exit codes: 0 success, 1 empty query result, 2 error.

## Invariants

- `tests/fixtures/complex_c_project` is never modified. It is the tool's own test subject.
- No new runtime dependencies. The standard library only.
- No SQLite schema change without a migration in `adapters/storage/migrations.py` and a version bump.
- Identical stored state produces identical parser output and report files.
- Source code never leaves the machine; AI stays disabled and optional.
- `ruff` and `mypy` stay clean.

## Where state lives

`.code-intelligence/` inside the target repository: `config.toml`,
`index.sqlite`, `repository.md`, `REQUIRED_INPUTS.md`, plus `input/`,
`context/`, and `reports/`.

## Commands

```bash
PYTHONPATH=src python3 -m unittest discover -s tests   # full suite
ruff check src scripts tests
mypy
python scripts/fixtures.py run complex_c_project       # fixture bootstrap and validation
```

## Docs

- `docs/IMPROVEMENT_PLAN.md`: phased work with status per phase.
- `docs/CODEBASE_AUDIT.md`: findings with file:line evidence.
- `docs/CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md`: what works today and what is next.
- `README.md`: user-facing setup and command reference.
