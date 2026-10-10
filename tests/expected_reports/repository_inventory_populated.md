# Repository Inventory

- Repository: `/repo`
- Scanned at: `2026-01-01T12:00:00+00:00`
- Files recorded: 4 *(calculated metric)*
- SHA-256 hashes computed: 2 *(calculated metric)*
- SHA-256 hashes reused: 2 *(calculated metric)*

## What this report means

This inventory is the scanner's snapshot of the repository: every relevant C source, header, and Make input found on disk, the per-file evidence recorded at scan time, the capabilities cintel claims, and a build-state summary from persisted build discoveries. `cintel scan` refreshes it incrementally; `cintel report` regenerates it from stored state.

## Value meanings

- *calculated metric*: derived from recorded rows, not a scanned field.
- Evidence `extracted fact`: the value existed on disk as recorded at scan time; `unavailable information` marks facts that cannot be claimed.
- Kind `c_source`/`c_header`: relevant C files; `makefile`/`make_fragment`: Make build inputs recognized by name; `other`: other recorded build-adjacent inputs.
- SHA-256: content hash of the file at scan time; the `Files` table shows a 12-character short form, and `repository.json` records the full hash.
- Capability status `available`/`degraded`/`unavailable` states what cintel can and cannot claim for this repository.

## Capabilities and limitations

- **make** — available: GNU Make found *(extracted fact)*

## Inventory summary

- c_source: 2 *(calculated metric)*
- c_header: 1 *(calculated metric)*
- makefile: 1 *(calculated metric)*
- make_fragment: 0 *(calculated metric)*
- other: 0 *(calculated metric)*

## Files by top-level directory

- `(root)`: 2 *(calculated metric)*
- `include`: 1 *(calculated metric)*
- `src`: 1 *(calculated metric)*

## Files

| Path | Kind | Bytes | SHA-256 (short) | Evidence |
|---|---:|---:|---|---|
| `main.c` | c_source | 10 | `aaaaaaaaaaaa` | extracted fact |
| `src/app.c` | c_source | 10 | `bbbbbbbbbbbb` | extracted fact |
| `include/app.h` | c_header | 10 | `cccccccccccc` | extracted fact |
| `Makefile` | makefile | 10 | `dddddddddddd` | extracted fact |

## Diagnostics

No scan diagnostics.

## Build-awareness status

- Persisted build configurations: 1 *(calculated metric)*
- Compilation units recorded: 2 *(calculated metric)*
- Files with analysis results: 3 *(calculated metric)*

Persisted build discoveries are integrated below and in the `build_selection` and `compilation_units` reports.

## Build configurations

- debug (target: `debug`)
