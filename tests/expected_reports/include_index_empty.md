# Include Index

- Include directives: 0 *(calculated metric)*
- Unresolved includes: 0 *(calculated metric)*

## What this report means

Every `#include` directive the conservative parser found in analyzed files, and whether it could be mapped to an actual file. Resolution uses the including file's directory plus the compilation unit's `-I` paths. Unresolved directives are listed first, grouped by spelling, so the headers the analysis cannot see are immediately visible; resolved directives follow, grouped by including file.

## Value meanings

- Included: the spelling exactly as written after `#include` (angle brackets and quotes included).
- Referenced from: the files holding the directive, with 1-based lines.
- Unresolved: no matching file in the search paths — typical for system headers (`<stdio.h>`) and generated headers that do not exist yet. This is an explicitly reported limit, not an error.
- Resolved: the found file's repository-relative path.

_No analyzed includes. Run `cintel analyze` first. (unavailable information)_