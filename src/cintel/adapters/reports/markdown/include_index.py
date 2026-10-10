"""Markdown rendering for the include_index report family.

Rendered from the typed report data assembled by
``cintel.application.reports``; the JSON sibling lives in
``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from cintel.adapters.reports.markdown.shared import (
    escape,
    require,
)
from cintel.domain.models import (
    IncludeIndexEntry,
    IncludeIndexReportData,
)


def render(data: IncludeIndexReportData) -> str:
    require(data, IncludeIndexReportData, "include_index")
    unresolved_entries = tuple(
        entry for entry in data.entries
        if entry.resolved_path is None
    )
    resolved_entries = tuple(
        entry for entry in data.entries
        if entry.resolved_path is not None
    )
    lines = [
        "# Include Index",
        "",
        f"- Include directives: {len(data.entries)} *(calculated metric)*",
        f"- Unresolved includes: {data.unresolved_count} "
        "*(calculated metric)*",
        "",
        "## What this report means",
        "",
        "Every `#include` directive the conservative parser found in "
        "analyzed files, and whether it could be mapped to an actual "
        "file. Resolution uses the including file's directory plus the "
        "compilation unit's `-I` paths. Unresolved directives are "
        "listed first, grouped by spelling, so the headers the "
        "analysis cannot see are immediately visible; resolved "
        "directives follow, grouped by including file.",
        "",
        "## Value meanings",
        "",
        "- Included: the spelling exactly as written after "
        "`#include` (angle brackets and quotes included).",
        "- Referenced from: the files holding the directive, with "
        "1-based lines.",
        "- Unresolved: no matching file in the search paths — "
        "typical for system headers (`<stdio.h>`) and generated "
        "headers that do not exist yet. This is an explicitly "
        "reported limit, not an error.",
        "- Resolved: the found file's repository-relative path.",
        "",
    ]
    if not data.entries:
        lines.append("_No analyzed includes. Run `cintel analyze` first. "
                     "(unavailable information)_")
    else:
        lines.extend(("## Unresolved includes", ""))
        if not unresolved_entries:
            lines.append("No unresolved include directives.")
            lines.append("")
        else:
            by_spelling: dict[str, list[IncludeIndexEntry]] = {}
            for entry in unresolved_entries:
                by_spelling.setdefault(entry.included_spelling, []).append(
                    entry
                )
            for spelling in sorted(by_spelling):
                references = sorted(
                    by_spelling[spelling],
                    key=lambda item: (
                        item.including_path,
                        item.line,
                    ),
                )
                lines.extend(
                    (
                        f"### `{escape(spelling)}` "
                        f"({len(references)} directives)",
                        "",
                    )
                )
                lines.append("Referenced from:")
                for entry in references:
                    lines.append(
                        f"- `{escape(entry.including_path)}:"
                        f"{entry.line}`"
                    )
                lines.append("")
        lines.append("## Resolved includes")
        lines.append("")
        if not resolved_entries:
            lines.append("No resolved include directives.")
            lines.append("")
        else:
            by_including: dict[str, list[IncludeIndexEntry]] = {}
            for entry in resolved_entries:
                by_including.setdefault(entry.including_path, []).append(
                    entry
                )
            for including_path in sorted(by_including):
                directives = sorted(
                    by_including[including_path],
                    key=lambda item: (item.line, item.included_spelling),
                )
                lines.extend(
                    (f"### `{escape(including_path)}`", "")
                )
                lines.append("Included:")
                for entry in directives:
                    # directives comes from resolved_entries, so the path is set.
                    resolved_path = entry.resolved_path
                    assert resolved_path is not None
                    lines.append(
                        f"- line {entry.line}: "
                        f"`{escape(entry.included_spelling)}` → "
                        f"`{escape(resolved_path)}`"
                    )
                lines.append("")
    return "\n".join(lines)
