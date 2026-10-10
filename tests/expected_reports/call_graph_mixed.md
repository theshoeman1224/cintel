# Call Graph

- Direct-call edges: 4 *(calculated metric)*
- Unresolved edges: 3 *(calculated metric)*

## What this report means

Direct calls extracted from analyzed function bodies and resolved deterministically: same-file `static` definitions win, then a single repository-wide definition, with callers using a build restricted to that build's files. It is organized one section per calling function so a function's callees read top-down; unresolved calls are listed separately, grouped by callee. Entry-point reachability and recursion findings derive from these edges.

## Value meanings

- Caller heading: the calling function and its defining file.
- Callee: the called function with its definition location when the call resolved to one definition.
- Call site: 1-based line of the calling expression.
- Resolution `confirmed_direct`: exactly one definition within scope addressed the call.
- Resolution `unresolved`: ambiguous (competing definitions), out of the analyzed set, or reached through machinery the conservative parser does not interpret (function pointers, macro-generated code). Unresolved edges are expected limits, not errors; grouping them by callee shows which names need external evidence.

## Calls by caller

### main (`src/main.c`)

Callees:
- `helper` (`src/util.c:1`) — call site 8

## Unresolved calls

### `(unknown callee spelling)` (1 call sites)

Called from:
- `(unresolved caller)` (`src/runner.c`:2)

### `callback` (1 call sites)

Called from:
- `main` (`src/main.c`:9)

### `missing` (1 call sites)

Called from:
- `runner` (`src/runner.c`:3)
