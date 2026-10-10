# CLI redesign brief

- Status: design only; nothing here is scheduled or implemented
- Created: 2026-10-10, from the CLI findings in `docs/CODEBASE_AUDIT.md`
- Constraint: no new runtime dependencies. Everything below must work with
  argparse and the standard library.

## Why this exists

The CLI grew command by command, and the seams show:

- global options such as `--repository` and `--config` only work before the
  subcommand, a rule argparse cannot express with one parser;
- `--build-config` defaults to `default`, so a user who discovered `debug`
  gets silently file-scoped analysis from a plain `analyze`;
- error text and JSON output have no shared shape, and errors never render as
  JSON;
- out-of-order commands fail by different conventions: `scan` auto-runs for
  `analyze` and `report`, but queries do not auto-run `analyze`;
- `show function`, `symbols`, and `build units` follow no single naming rule;
- no command answers "what is the state of this workspace?".

Phase 2 patched the sharp edges. This brief is the structural fix.

## Target shape

### Options and placement

Move every global option onto argparse parent parsers shared by the
subparsers, so both spellings work:

```bash
cintel --repository ./src scan
cintel scan --repository ./src
```

Keep the old spelling working permanently. Parent parsers make the duplicate
definitions trivial, so nothing needs deprecating.

### A status command

`cintel status` prints one screen of workspace state and never mutates it:

- repository root and which config source won (flag, conventional file, or
  defaults);
- scan freshness: file count, last scan time, whether files changed since;
- build configurations with unit counts and cache state;
- analysis state: analyzed files, stale files, last run status;
- report freshness and the path of REQUIRED_INPUTS.md;
- pending evidence: which capabilities are missing and the next command.

Exit codes: 0 when the workspace is complete, 1 when evidence is missing but
analysis is usable, 2 when the workspace is unusable. `--json` returns the
same data as a structured object. This is the first command a user or agent
runs, and the rest of the redesign hangs off it.

### Prerequisite policy

Make the policy explicit instead of accidental:

| Command | Missing prerequisite | Behavior |
|---|---|---|
| `scan` | workspace | create it silently |
| `analyze` | scan | auto-scan |
| `report` | analyze | generate from stored state and warn |
| queries, context | analyze | print a `cintel analyze` hint, exit 1 |
| `build units`, `build show` | discovery | hint at `build discover`, exit 1 |
| `build discover` | none | never auto-run make; always preview and warn |

This is already the behavior after Phase 2. The redesign documents it in
help text and adds a `cintel status` pointer to each hint.

### Build configuration selection

- `status` lists configuration names with unit counts.
- When `analyze` or `build units` finds no units for the requested name but
  other configurations exist, print their names.
- Consider defaulting to the only configuration when exactly one exists,
  instead of the literal `default`.

### JSON envelope

One envelope for every command:

```json
{
  "schema": 1,
  "command": "analyze",
  "status": "ok",
  "data": {},
  "diagnostics": [],
  "error": null
}
```

`status` is `ok`, `empty`, or `error`. Errors use the same envelope with
`error` set, so scripts parse one shape. Exit codes stay 0, 1, and 2. This is
a breaking change for `--json` consumers, so it ships with a release note and
the fixture validator moves in the same change.

### Config precedence

State and implement one order:

1. `--config PATH` wins outright.
2. Otherwise `<repository>/.code-intelligence/config.toml`.
3. `--output-directory` overrides the config's output and database paths.
4. Otherwise built-in defaults for the repository root.

Phase 2 already made steps 2 and 3 compose. The redesign adds `--print-config`
to show which source won, and logs the choice to stderr under `--verbose`.

### Naming pass

Proposal:

- `symbols` stays;
- `show function` becomes `symbol show <name>`;
- `callers` and `callees` become `symbol callers <name>` and
  `symbol callees <name>`;
- `context function` becomes `context <name>`;
- `build units` and `build show` keep their names.

Rule: verb first, entity second. Every old spelling stays as a hidden alias
for at least one release.

### Interactive setup wizard

`start.sh` proves the wizard flow works; move it into the CLI as
`cintel setup --interactive` so Windows and non-bash users get the same path:

- detect the environment and missing evidence;
- offer live Make, imported evidence, or file-scoped analysis;
- preview the exact commands before running them;
- write REQUIRED_INPUTS.md when evidence is still missing.

Keep `start.sh` as a bootstrap that installs and then calls the wizard.

### Shell completion

No runtime dependency is allowed, so ship static completion scripts generated
from the parser at release time:

- a `scripts/completions.py` that walks `build_parser()` and writes bash and
  zsh completion files;
- sourcing instructions in the README;
- regeneration in CI that fails when the committed files drift.

## Compatibility and rollout

- Exit codes 0, 1, and 2 are frozen.
- Every renamed command keeps an alias for at least one release.
- The JSON envelope carries `schema`; changes bump it.
- Suggested order: status command, envelope, aliases, wizard, completion.

## Non-goals

- No network calls.
- No AI in the deterministic path.
- No new runtime dependencies, including completion libraries.
- No full-screen TUI; plain text and JSON only.
