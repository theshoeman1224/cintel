# Documentation alignment audit and plan

- Audit date: 2026-10-21
- Audited revision: `8e773bb` (`main`, clean tree)
- Scope: every Markdown doc (`README.md`, `AGENTS.md`, `docs/*.md`,
  `.portfolio/*`, `tests/fixtures/README.md`, the complex fixture's README and
  `EXPECTED_FINDINGS.md`), the source under `src/cintel`, the tests and
  fixtures, `scripts/install.py`, `scripts/fixtures.py`, and `start.sh`
- Method: read the docs first and listed every testable claim, then checked
  each claim against the code and by running the tool. All live runs used
  disposable copies of `tests/fixtures/complex_c_project` in a scratch
  directory, so the committed fixture was not touched.

## What the project is

`cintel` is an offline, standard-library-only Python CLI that indexes legacy C
repositories while keeping track of the build. The pipeline is `init`,
`doctor`, `scan`, then `build discover` (GNU Make `-n -B`) or `resume` with
imported evidence, then `analyze` (a conservative lexical parser with
deterministic call and include resolution), and finally the read side:
`symbols`, `show function`, `callers`, `callees`, `context function`, and
`report`. State lives in SQLite under `.code-intelligence/`. The docs describe
the deterministic MVP as complete through Phase 6. Optional GCC enrichment
(Phase 7) is the next planned slice.

## What was run

| Check | Result |
|---|---|
| `PYTHONPATH=src python -m unittest discover -s tests` | 297 pass (243 unit, 54 integration), 0 skipped, Make 4.4.1 and GCC 15.2 present |
| `ruff check src scripts tests` | clean |
| `mypy` | clean, 81 files |
| `scripts/install.py` in the existing `.venv` | skips correctly (version already installed, editable) |
| `scripts/install.py` in a fresh venv (Python 3.14) | installs; the `cintel` entry point works outside the repo |
| `start.sh`, option 3 (no build evidence) | works, exit 0 |
| `start.sh`, option 1 (live Make, target `linux`) | works, exit 0, 19 units |
| `start.sh`, option 1 (blank target, default goal) | works, exit 0 |
| `start.sh`, option 2 (saved `make-linux-dry-run.txt`) | works, exit 0, 19 units recovered |
| `start.sh`, option 2 (`verbose-build.log`) | exit 0, but the log is ignored and analysis drops to file-scoped (see S4) |
| `start.sh` with a nonexistent path | dies with a raw `cd` error (see S1) |
| `scripts/fixtures.py list` | works |
| `scripts/fixtures.py run complex_c_project` | passes, but validates only 13 findings (see F1) |
| Full documented flow plus `report`, validated by the fixture's validator | passed=29, missing=0, conflicts=0, heuristic=4, unsupported=2 |

These README claims were checked and hold: the command table, exit codes
0/1/2, the JSON error object, the `Action:` lines, the global-option
placement rule, Make caching (`Source: cache` on the second run), the
non-TTY preview and warning, the report families and their file locations,
the "What this report means" and "Value meanings" sections on every Markdown
family, generated-report metadata rows (including `function_context:*` and
`required_inputs`), byte-identical reports apart from the timestamped
inventory, context file naming and budget behavior, schema v6, the
diagnostic code list, default exclusions, `shell=False`, and the
single-module imports of `subprocess` and `sqlite3`.

## Findings

Severity: **High** means the tool gives wrong or contradictory results, or a
documented path is broken. **Medium** means the code and docs disagree in a
way a user or agent will notice. **Low** means stale wording or polish.

### Code behavior that contradicts the docs

**C1 (High). Queries and reports merge analysis scopes and show
contradictory call edges.** The roadmap says "queries collapse those
duplicates by source location, so every symbol is presented once." Repro:
run `build discover --build-config linux`, then `--build-config linux
analyze`, then a plain `analyze`. After that,
`callees main --file src/app/main.c` lists 9 edges, and `platform_name` and
`platform_shutdown` each appear twice: once as `confirmed_direct` and once
as `unresolved`, for the same call site. `reports/call_graph.json` has the
same pair of edges and no field saying which configuration produced each
one. File-scoped results and build-configured results both persist, and the
query and report layers (`application/queries.py:159-200`,
`application/reports.py:449-520`) union them.

Status 2026-10-21: fixed. `analyze` records its build configuration in the
`source_analysis` workflow state. The new `application/analysis_scope.py`
rebuilds that run's result set, and queries and every analysis-derived report
family read only that set. `analyze` also re-resolves file-scoped calls that
still pointed at another configuration's definition. The regression test is
`test_queries_and_reports_follow_the_latest_analysis_scope` in
`tests/integration/test_analysis.py`. The planned `configuration` field on
report entries was not needed and was not added.

**C2 (Medium). `--verbose` does nothing.** The help text says "Print extra
progress detail to standard error" (`cli/main.py:91`). No code reads
`args.verbose`. Phase 2 removed its only use when the Make preview became
unconditional. `docs/CLI_REDESIGN_BRIEF.md` also plans more `--verbose`
logging.

Status 2026-10-21: fixed in Phase 4. `--verbose` prints the configuration
source and the command's run time to standard error.

**C3 (Medium). Interactive `build discover` prints the preview twice.** On a
TTY, the evaluation command and the `$(shell ...)` warning print twice,
because the unconditional block (`cli/main.py:378-388`) is followed by a
duplicate `if interactive:` block (`cli/main.py:389-399`). Reproduced under
`script`. The README promises one preview followed by a confirmation.

Status 2026-10-21: fixed in Phase 1. The duplicate block is gone, and
`test_interactive_build_discover_previews_once` checks that the preview
prints exactly once.

**C4 (Medium). `doctor` always recommends `cintel init`.** When no other
action applies, `application/doctor.py:133-134` appends "Run
`cintel init <repository>`", even right after `init` succeeded. `start.sh`
prints this on every run.

Status 2026-10-21: fixed in Phase 1. `doctor` recommends `init` only when
`config.toml` is missing, and otherwise points at `scan` and
`build discover` or `setup`.

**C5 (Medium). `doctor` reports `gcc_enrichment: available`.** The README
and roadmap both say GCC enrichment is not implemented (Phase 7).
`application/doctor.py:240-244` marks the capability available whenever a
GCC executable exists.

Status 2026-10-21: fixed in Phase 1. `gcc_enrichment` is always
`unavailable`, and the reason says whether GCC was found. GCC still appears
under `Tools:`.

**C6 (Medium). The `--build-config` default silently changes results.** The
help text documents the `default` default, but after
`build discover --build-config linux`:

- `build units` prints "Run `cintel build discover` first", although
  discovery has run;
- plain `analyze` falls back to file-scoped analysis with no hint, which
  then triggers C1.

The 2026-10-10 audit lists this as finding 8 and marks it fixed. Only the
help text changed.

Status 2026-10-21: fixed in Phase 1. `build units` and `build show` name the
requested configuration and list the discovered ones. `analyze` adds an
info-level `CI-ANLZ-001` diagnostic with the same list instead of falling
back silently. The `default` default is unchanged.

**C7 (Low). Read-only commands create a workspace.** AGENTS.md says queries
"read persisted state only". `symbols` on a fresh directory creates
`.code-intelligence/index.sqlite`.

Status 2026-10-21: fixed in Phase 4. Queries, `context`, `build units`, and
`build show` check for the database first. Without it they exit 1 with an
init hint (`WorkspaceNotFound` under `--json`) and create nothing.

**C8 (Low). `report` is not read-only.** AGENTS.md groups `report` with the
read-only queries. `ReportService.generate_all` re-scans the repository and
rewrites the inventory (`application/reports.py:113`). The README's
"regenerates every report family from persisted state" is accurate for the
families under `reports/`, but not for the inventory.

Status 2026-10-21: documented. AGENTS.md has said since PR #7 that `report`
re-scans, and since Phase 4 that it creates the workspace if needed. The
behavior is intentional and was not changed.

**C9 (Low). `[ai] enabled = true` is ignored without a warning.** The loader
reads the value (`configuration/loader.py:49`) and nothing checks it. The
README says future providers must require explicit approval. A user who sets
the flag gets no signal that it does nothing.

Status 2026-10-21: fixed in Phase 4. Every command warns on standard error,
and `doctor` reports the new `CI-CONF-001` warning diagnostic.

### `start.sh` against README and IMPROVEMENT_PLAN

**S1 (High). A bad repository path still crashes the script.** Line 122,
`REPO="$(cd "$REPO" && pwd)"`, runs under `set -e`. The script exits with a
raw `cd: ... No such file or directory`, and the friendly check two lines
later never runs. IMPROVEMENT_PLAN Phase 2 and audit finding 11 both say
this was fixed.

Status 2026-10-21: fixed. A `resolve_repository` helper validates the path,
and the script re-prompts until it gets an existing directory. If input ends,
it exits 1. A sourcing guard lets `tests/unit/test_start_script.py` load the
helpers without running the setup.

**S2 (Medium). The default demo path writes into the committed fixture.**
The default repository path is `tests/fixtures/complex_c_project` (line
120). Accepting it creates `.code-intelligence/` inside the fixture. A stale
copy from 2026-10-10 is there now. It is gitignored, but this conflicts with
the README ("Copy it before running the full flow so the committed fixture
stays untouched") and with the AGENTS.md invariant.

Status 2026-10-21: fixed in Phase 2. Choosing the fixture analyzes a
disposable copy at `.fixture-output/demo/complex_c_project`, created by
`prepare_demo_copy` without `.code-intelligence/`, `build/`, or generated
outputs, then filled by `make generate CONFIG=linux` when Make exists. The
copy is reused on re-runs.

**S3 (Medium). The import path hard-codes the build configuration
`debug`.** Option 2 never asks for a configuration name, Makefile, or target
(lines 157 and 244). Importing the Linux dry-run stores it as `debug`, and
the suggested next steps say `--build-config "debug"`.

Status 2026-10-21: fixed in Phase 2. Option 2 prompts for the configuration
name, Makefile, and target.

**S4 (Medium). The import menu says "saved dry-run/build log"** (line 162),
and the prompt offers all six input types. Only `make_dry_run` produces
compilation units. A build log validates, is then ignored, and analysis
falls back to file-scoped. The roadmap documents that only dry-runs are
consumed; `start.sh` and the README's description of it do not.

Status 2026-10-21: fixed in Phase 2. The menu offers an imported `make -n`
transcript, and the prompt says only `make_dry_run` enables build-aware
analysis. Other types are imported with a note, and the script no longer
attempts build-aware analysis for them.

**S5 (Low). Misleading messages.** "Note: ... see REQUIRED_INPUTS.md below"
does not print the file. "Using interpreter: python3.12" appears while the
script reuses a Python 3.14 venv.

Status 2026-10-21: fixed in Phase 2. The note prints the full
`REQUIRED_INPUTS.md` path. The script reports the interpreter it found and,
separately, the virtualenv's interpreter.

### Fixtures and tests against their docs

**F1 (High). `scripts/fixtures.py run complex_c_project` skips every
analysis finding.** The README, `tests/fixtures/README.md`, and the fixture
README all say `run` validates against `expected_findings.json`. The hook
(`tests/fixtures/complex_c_project/fixture.py:66-128`) never runs `report`
and never passes `analysis_report` to the validator. As a result, 17
mandatory findings (functions, globals, types, calls, includes) are reported
as "not exported by current cintel phase". The driver passes with
`passed=13`. IMPROVEMENT_PLAN Phase 6 records `passed=13` as its
verification result. The integration test does the full flow and gets 29.

Status 2026-10-21: fixed, with the maintainer's one-time permission to edit
`fixture.py`. `run` now calls `report`, passes the four analysis families to
the validator, and fails if any finding is labelled "not exported". The
driver now reports `passed=29`. The guard is
`test_complex_run_validates_analysis_findings` in
`tests/integration/test_fixture_driver.py`.

**F2 (Medium). The test suite mutates the committed fixture directory.**
`tests/integration/test_complex_fixture.py:220-228` runs
`tools/verify_fixture.py` in place. The script writes `build/` and
`generated/`, and it rewrites the committed files under
`expected/sample_inputs/` (`verify_fixture.py:176-177`). Today the output is
byte-identical, so git stays clean. A different Make or GCC version would
leave the tree dirty after a test run. `tests/fixtures/README.md` says these
artifacts are produced "only by `setup`".

Status 2026-10-21: fixed for the test suite. The live test copies the
fixture, runs `verify_fixture.py` on the copy, and checks that every
committed fixture path and its modification time are unchanged afterwards.
The driver's `verify` operation still runs in place by design, and
`tests/fixtures/README.md` now says so.

Status 2026-10-21, Phase 3: the driver's `verify` now runs on an exact
temporary copy too (`scripts/fixtures.py`, `_execute`). No fixture file
changed.

**F3 (Low). Python 3.11 is never tested.** `requires-python = ">=3.11"`,
and the README says to use `python3.11`. Both CI workflows run only 3.12.

Status 2026-10-21: fixed in Phase 3. `quality.yml` runs ruff, mypy, and the
suite on a 3.11 and 3.12 matrix.

### Documentation that disagrees with itself or is stale

| ID | Where | Problem |
|---|---|---|
| D1 | `README.md` "Reports" | Lists 7 families and leaves out `symbol_index` and `global_usage`. The code and roadmap generate 9 (20 files including the inventory). |
| D2 | `README.md` "Adding adapters" | Says to implement `CompilerProvider` to add a compiler adapter. Nothing implements or consumes it. The real seams are `CompilerCommandParser` and `CompilerMetadataProvider`. `AIProvider` has no consumer either. |
| D3 | `AGENTS.md` "Command flow" | Lists `report` as reading persisted state only (C8) and says queries read only (C7). |
| D4 | `AGENTS.md` "Docs" | Leaves out `REFACTOR_PLAN.md` and `CLI_REDESIGN_BRIEF.md`. |
| D5 | Roadmap header | Gives "Audit date 2026-08-10, re-verified 2026-08-30" and revision `83294e9`, while the body says re-verified 2026-10-10. |
| D6 | Roadmap "Verification baseline" | Says 275 tests (223 unit / 52 integration); actual is 297 (243 / 54). Says the fixture gives 28 passed; actual is 29. |
| D7 | Roadmap architecture table | "Application services: Phases 1–5B" leaves out queries, context, and reports. "SQLite adapter: implemented through Phase 5A" contradicts the schema v6 text in the same row. |
| D8 | Roadmap executive summary | "Phase 5A adds ... Schema version 6 stores ..." attributes the Phase 6 schema to Phase 5A. |
| D9 | `IMPROVEMENT_PLAN.md` definition of done | Says "All six phases ... at 275 tests". There are seven phases (0–6), and Phase 6 ends at 297. Phase 6 says "the working tree was left uncommitted", but it was committed in `3a269bf`. |
| D10 | `IMPROVEMENT_PLAN.md` Phase 2, `CODEBASE_AUDIT.md` | "All twelve findings are fixed." Finding 11 (`start.sh` bad path) is still open (S1). Finding 8 (`--build-config` default) is only documented (C6). |
| D11 | `CLI_REDESIGN_BRIEF.md` | "errors never render as JSON" has been stale since Phase 2. The prerequisite table says it is "already the behavior" but leaves out that queries create a workspace (C7). |
| D12 | `.portfolio/project.yaml` | Says "cross-file resolution and end-user analysis queries remain active roadmap work". Both shipped. |
| D13 | `.portfolio/architecture.md` | The application component list stops at guided recovery. The data-flow section describes reports before the analysis that produces them. |
| D14 | `README.md` "Quickest start" vs "Example repository" | One says the fixture "works as a demo" in place; the other says to copy it first (S2). |
| D15 | `tests/fixtures/README.md` | Says `build/` and `generated/` are produced "only by `setup`", but the test suite also produces them (F2). |
| D16 | `REFACTOR_PLAN.md` | Says `list_build_configurations` "stays as a declared port seam" with no caller. `application/reports.py` now calls it. Historical, but misleading to an agent. |

### Polish noticed along the way (not mismatches)

- Discovery prints the same `CI-BUILD-005` line 19 times without naming the
  file, because the text renderer drops `related_paths`.
- The interactive confirmation appears even when a cached discovery would
  not run Make at all.
- A stale `src/legacy_c_code_intelligence.egg-info/` (gitignored) holds an
  old copy of the README.

## Plan

The ground rules match the earlier plans:

- `tests/fixtures/complex_c_project` is not modified unless the maintainer
  grants an exception (see Phase 3).
- The suite, ruff, and mypy stay green after every phase.
- Every behavior change lands with a test that failed before it.
- No schema bump. No runtime dependencies.
- Each phase ends with the doc updates listed under it.

### Phase 1: correctness bugs (code)

Status: complete (2026-10-21). C1 landed earlier in PR #7; C3–C6 landed in
this phase, each with a test that failed first. Two parts of the original C1
plan were dropped: queries follow the latest `analyze` scope and take no
`--build-config` override (rerunning `analyze` is cheap thanks to reuse),
and report entries carry no `configuration` field, because a report now
covers exactly one scope.

1. **C1, scoped analysis results.** Give every query and report one analysis
   scope instead of a union.
   - Persist which build configuration the latest `analyze` used. The
     existing `analysis` workflow-state `details` can hold it, so no schema
     change is needed.
   - Queries and `report` read that scope by default. `--build-config`
     overrides it. File-scoped results for files outside the build stay
     visible.
   - Add a `configuration` field to `call_graph`, `include_index`, and
     `function_index` entries in both formats. This changes golden snapshots,
     so update `tests/expected_reports/` in the same commit.
   - Regression test: discover `linux`, analyze `linux`, analyze plain, then
     assert `callees main` has one edge per call site and no
     resolved/unresolved pair.
2. **C3.** Delete the duplicate `if interactive:` block at
   `cli/main.py:389-399`. Test by patching `sys.stdin.isatty` and `input`,
   then assert stderr has the command exactly once.
3. **C4.** `doctor` checks whether `config.toml` exists. It recommends
   `init` only when it is missing, and otherwise recommends `scan` (or the
   next incomplete workflow stage).
4. **C5.** Report `gcc_enrichment` as `unavailable` with the reason "GCC
   found; enrichment is not implemented yet (Phase 7)". Keep tool detection
   in the `Tools:` list. Update `test_doctor.py`.
5. **C6.** When the requested configuration has no units but others exist,
   `build units`, `build show`, and `analyze` name the existing
   configurations in the hint. `analyze` emits an info diagnostic instead of
   switching silently. This is the brief's "Build configuration selection"
   item, pulled forward.

Docs: README "Symbol and relationship queries" and "Reports" (scope rule and
the new `configuration` field), roadmap "Symbol, call-graph" section, and the
brief's build-configuration section (mark it done).

### Phase 2: `start.sh` (script)

Status: complete (2026-10-21). S1 landed in PR #7 as a re-prompting
`resolve_repository` helper instead of the `exit 1` sketched below. S2–S5
landed in this phase. `tests/unit/test_start_script.py` covers the demo-copy
helper. Manual runs of the demo default (live Make and imported dry-run)
left the committed fixture's paths and mtimes unchanged.

1. **S1.** Replace line 122 with a guarded
   `if ! REPO="$(cd "$REPO" 2>/dev/null && pwd)"; then ...; exit 1; fi`.
   Add a shell test, or extend `test_install_script.py`, that runs the
   script with piped answers and a bad path, then asserts the friendly
   message and exit 1.
2. **S2.** When the user accepts the demo default, copy the fixture to
   `.fixture-output/demo/` (gitignored, already used by the driver), leaving
   out `.code-intelligence/` and `build/`, and analyze the copy. Then run
   `make generate CONFIG=linux` in the copy when Make is available, so the
   demo doesn't open with 19 missing-forced-include warnings.
3. **S3.** Option 2 asks for a build configuration name and passes the
   Makefile and target, as option 1 does.
4. **S4.** Option 2 states that only `make_dry_run` produces build-aware
   analysis. Other types are imported for the record, and the script says
   so before falling back to file-scoped analysis.
5. **S5.** Print the venv interpreter's version when the script reuses the
   venv. Change "see REQUIRED_INPUTS.md below" to print the file's path.

Docs: README "Quickest start" (copy behavior, configuration prompt, accepted
input types). Reopen and then close audit finding 11 in `CODEBASE_AUDIT.md`.

### Phase 3: fixture and test alignment

Status: complete (2026-10-21). F1 and F2 landed in PR #7. F2 used an
mtime snapshot of the fixture instead of `git status`, because rewrites with
identical content leave git clean. F1 fails on any "not exported" finding
rather than on a numeric floor. In this phase, the driver's `verify` moved
onto a temporary copy, so no further `fixture.py` edit was needed. The CI
matrix landed, and the generated `build/`, `generated/`, and stale
`.code-intelligence/` were cleaned out of the local fixture. The suite no
longer recreates them.

1. **F2 (no exception needed).** Change
   `test_fixture_builds_and_current_cintel_subset_validates` to copy the
   fixture into a temporary directory and run `verify_fixture.py` there.
   Assert that `git status --porcelain tests/fixtures` is empty after the
   test, so the invariant is enforced instead of assumed.
2. **F1 (needs a decision).** The fix is three lines in `fixture.py`: run
   `report` after `analyze`, then add the four analysis JSON families to the
   envelope. That file is inside the protected directory. There are two
   options:
   - **(a) Recommended: a one-time, documented exception.** `fixture.py` is
     driver glue, not part of the test subject. Narrow the AGENTS.md
     invariant to "fixture sources, expectations, and tools" and fix it in
     place.
   - **(b) Keep the invariant absolute.** Teach `scripts/fixtures.py` to
     prefer an override hook at `scripts/fixture_hooks/<name>.py`, and move
     the corrected `run` there.

   With either option, make `run` fail unless `passed` meets a floor (29
   today) so the gap can't reopen silently. `verify` has the same
   in-place-write problem as F2. Fixing it the same way needs the same
   decision.
3. **F3.** Add a Python 3.11 and 3.12 matrix to `quality.yml`.
4. Locally: run `python scripts/fixtures.py clean complex_c_project` and
   remove the stale `tests/fixtures/complex_c_project/.code-intelligence/`.

Docs: `tests/fixtures/README.md` (who writes in place), README "Test
fixtures", and the fixture tally in the roadmap.

### Phase 4: small CLI contract fixes

Status: complete (2026-10-21). C2, C7, and C9 landed with tests that failed
first, and so did the optional diagnostic grouping: 19 identical
`CI-BUILD-005` lines now print once with a count and the missing file's
path. `--verbose` was kept and implemented rather than removed. Two
SonarCloud follow-ups came with it: coverage now measures `scripts/` (Sonar
already listed it as source, so its new lines counted as uncovered), and
one S8495 smell in the new analysis helper was fixed.

1. **C2.** Make `--verbose` do what the help says: print to stderr which
   config source won (flag, conventional file, or defaults), plus stage
   timings for `build discover`, `analyze`, and `report`. If you'd rather
   not add output, remove the flag instead. It is unused, so removing it
   breaks no internal caller, but it would break external scripts that pass
   it.
2. **C7.** Queries, `context`, and `build units`/`show` open storage only
   when the database file exists. Otherwise they print the `cintel init`
   hint and exit 1. Add a test asserting that no `.code-intelligence/`
   appears.
3. **C9.** A config with `[ai] enabled = true` produces a warning diagnostic
   saying AI integration is not implemented and nothing will be sent.
4. Optional polish: group repeated diagnostics with a count and their
   related paths in the text renderer.

Docs: README "Exit codes and output" and the help text for `--verbose`,
AGENTS.md command flow (C7, C8).

### Phase 5: documentation sync (docs only)

Fix D1–D16 in one pass, after Phases 1–4 so the numbers are final:

- README: the full report family list (D1), the adapter section naming the
  real compiler seams and marking `CompilerProvider`/`AIProvider` as
  reserved (D2), and the demo wording (D14).
- AGENTS.md: the command-flow read/write split (D3) and the complete doc map
  including this file (D4).
- Roadmap: header date and revision (D5), test and fixture counts (D6), the
  architecture table (D7), and the executive summary phase attribution (D8).
- IMPROVEMENT_PLAN and CODEBASE_AUDIT: correct the phase count, test count,
  and commit note (D9). Mark findings 8 and 11 as reopened, then fixed by
  this plan (D10).
- CLI_REDESIGN_BRIEF: drop the stale JSON-error claim and update the
  prerequisite table (D11).
- `.portfolio/`: the summary (D12) and the component list and data-flow
  order (D13).
- `tests/fixtures/README.md` (D15). Add a one-line historical note in
  REFACTOR_PLAN (D16).

Consider extending `tests/unit/test_documentation.py` with cheap drift
guards: the README report list equals `_REPORT_FAMILIES`, and every flag in
`build_parser()` appears in the README or has help text that is not a
placeholder.

### Order and effort

Phases 1 to 3 hold every High finding and can land in that order. Phase 1
item 1 (C1) is the only change with design weight. Everything else is small
and local. Phase 5 should land last so the counts it records are final.
