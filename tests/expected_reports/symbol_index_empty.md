# Symbol Index

- Symbols recorded: 0 *(calculated metric)*

## What this report means

Named things the conservative parser found while analyzing source files: functions, file-scope variables, named types, and macros. It is organized one section per kind with symbols alphabetized by name, so a symbol lookup needs no scanning; `symbol_index.json` keeps location order for machine consumption. This is the lookup table behind `cintel symbols` and the store behind `symbol_index.json` fixture validation.

## Value meanings

- Sections: `function`, `variable` (file-scope objects), `type` (structs, unions, enums, typedefs, opaque types), `macro` (`#define`).
- State: `definition` (the parser saw the full body/type), `declaration` (extern prototypes, extern/forward types), `n/a` for symbols without a definition/declaration split.
- Location: repository-relative path and 1-based line.
- Rows are deduplicated by source location across analyzed scopes; queryable via `cintel symbols [--kind ...]`.

_No analyzed symbols. Run `cintel analyze` first. (unavailable information)_