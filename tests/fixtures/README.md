# Test fixtures

Fixtures live in this directory. `tests/fixtures/make/` is a data-only
collection of saved Make transcripts; every runnable fixture provides a
`fixture.py` that hooks it into the fixture driver.

## Driving fixtures

The driver (`scripts/fixtures.py`) discovers every `fixture.py` here
automatically:

```bash
python scripts/fixtures.py list                      # what exists, what it needs
python scripts/fixtures.py setup complex_c_project   # prepare generated artifacts
python scripts/fixtures.py verify all                # fixture self-checks
python scripts/fixtures.py clean all                 # remove generated artifacts
python scripts/fixtures.py run complex_c_project     # full end-to-end lifecycle
```

`run` bootstraps the environment through `scripts/install.py` (the same step
`start.sh` performs), copies the fixture to a disposable workspace, drives the
documented `cintel` CLI flow (`init`, `doctor`, `scan`, `build discover`,
`analyze`), and validates the results against the fixture's expected findings.
Committed fixture sources are never modified; only gitignored artifacts
(`build/`, `generated/`) are produced in place, and only by `setup`.

Useful flags for `setup`/`verify`/`clean`/`run`:

- `--output-dir DIR` — where `run` writes reports and the validation envelope
- `--no-bootstrap` — skip the `scripts/install.py` step
- `--python PATH` — interpreter used for cintel and fixture tools
  (defaults to `.venv/bin/python` when present, otherwise `sys.executable`)
- `-v` — print commands and captured output

## Adding a new fixture

Create a directory here with your fixture files plus a `fixture.py`. The
driver picks it up with no changes to the driver itself.

`fixture.py` may define any subset of:

```python
DESCRIPTION = "One-line summary shown by `list`."
REQUIRES = ("make", "gcc")          # executables checked with shutil.which

def setup(context): ...   # prepare the fixture (builds, generated inputs)
def verify(context): ...  # self-check: structure, expectations, no stray state
def clean(context): ...   # remove generated artifacts
def run(context): ...     # full lifecycle; raise on failure, return nothing
```

`context` is a `FixtureContext` (see `scripts/fixtures.py`) providing:

- `context.fixture_root` / `context.repo_root` — `pathlib.Path` locations
- `context.run(command, cwd=..., timeout=..., check=..., env=...)` — captured
  subprocess helper that raises on non-zero exit by default
- `context.cintel(arguments)` — runs `python -m cintel ...` with the `src`
  layout on `PYTHONPATH`, so it works exactly like the documented CLI
- `context.copy_to_tempdir()` — context manager yielding a disposable copy of
  the fixture (`.code-intelligence/` and `build/` excluded)
- `context.output_dir` — the `--output-dir` requested on the command line

Any operation you omit gets a sensible default (for example, `clean` falls
back to removing a stray `.code-intelligence/` directory). Operations should
report progress with `print("  ...")` and raise on failure; the driver prints
a per-fixture summary and exits non-zero if any fixture failed.

Fixture invariants (see `docs/CODEBASE_AUDIT.md` and
`docs/REFACTOR_PLAN.md`): committed fixture files must not be modified by
tooling, and anything a fixture generates must be gitignored.
