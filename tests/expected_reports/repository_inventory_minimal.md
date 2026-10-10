# Repository Inventory

- Repository: `/repo`
- Scanned at: `2026-01-01T12:00:00+00:00`
- Files recorded: 0 *(calculated metric)*
- SHA-256 hashes computed: 0 *(calculated metric)*
- SHA-256 hashes reused: 0 *(calculated metric)*

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
- **gcc** — unavailable: no C compiler on PATH *(unavailable information)*

## Inventory summary

- c_source: 0 *(calculated metric)*
- c_header: 0 *(calculated metric)*
- makefile: 0 *(calculated metric)*
- make_fragment: 0 *(calculated metric)*
- other: 0 *(calculated metric)*

## Files by top-level directory

_No relevant files were available. (unavailable information)_

## Files

_No relevant files were available. (unavailable information)_

## Diagnostics

- **CI-REPO-001** (warning): repository root is not readable
  - Details: Permission denied.
  - Suggested action: Run `cintel doctor`.
  - Suggested action: Check the mount.
- **CI-BUILD-001** (info): make was not found

## Build-awareness status

No persisted build discoveries are recorded for this repository yet, so this inventory cannot report build membership. Run `cintel build discover` to record build configurations, per-file compiler flags, and exact compiler arguments. *(unavailable information)*
