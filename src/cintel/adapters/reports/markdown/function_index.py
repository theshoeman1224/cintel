"""Markdown rendering for the function_index report family.

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
    FunctionIndexEntry,
    FunctionIndexReportData,
)


def render(data: FunctionIndexReportData) -> str:
    require(data, FunctionIndexReportData, "function_index")
    lines = [
        "# Function Index",
        "",
        f"- Definitions: {data.definition_count} *(calculated metric)*",
        f"- Declarations: {data.declaration_count} *(calculated metric)*",
        "",
        "## What this report means",
        "",
        "Functions the conservative parser extracted from analyzed "
        "source files — every declared or defined function name, where "
        "it lives, its linkage, and whether cintel saw a full "
        "definition. It is organized one heading per file so a file's "
        "functions are read top-down without consulting the "
        "scanner's file list; a flat, file-ordered view remains in "
        "`function_index.json`. It is the lookup table behind "
        "`cintel show function` and the context packages.",
        "",
        "## Value meanings",
        "",
        "- State `definition`: a complete function body was parsed; "
        "`declaration`: only a prototype (signature) was seen.",
        "- Linkage: `internal` (`static`), `external` (default), or "
        "`unknown` when the parser could not decide.",
        "- Location: repository-relative path and 1-based line of the "
        "definition or declaration.",
        "- Same function may appear once per analyzed scope; rows are "
        "deduplicated by source location.",
        "",
    ]
    if not data.entries:
        lines.append("_No analyzed functions. Run `cintel analyze` first. "
                     "(unavailable information)_")
    else:
        by_file: dict[str, list[FunctionIndexEntry]] = {}
        for entry in data.entries:
            by_file.setdefault(entry.relative_path, []).append(entry)
        for relative_path in sorted(by_file):
            entries = sorted(
                by_file[relative_path],
                key=lambda item: (item.line, item.name),
            )
            lines.extend(
                (f"## `{escape(relative_path)}`", "")
            )
            for entry in entries:
                state = "definition" if entry.is_definition else "declaration"
                lines.append(
                    f"- {entry.name} — {state}, {entry.linkage}, "
                    f"`{escape(entry.relative_path)}:{entry.line}`"
                )
            lines.append("")
    return "\n".join(lines)
