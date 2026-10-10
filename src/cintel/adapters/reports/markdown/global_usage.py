"""Markdown rendering for the global_usage report family.

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
    GlobalUsageIndexEntry,
    GlobalUsageReportData,
)


def render(data: GlobalUsageReportData) -> str:
    require(data, GlobalUsageReportData, "global_usage")
    by_variable: dict[str, list[GlobalUsageIndexEntry]] = {}
    for entry in data.entries:
        by_variable.setdefault(entry.variable, []).append(entry)
    functions_touching = {
        (entry.function, entry.function_path) for entry in data.entries
    }
    lines = [
        "# Global Usage",
        "",
        f"- Recorded usages: {len(data.entries)} *(calculated metric)*",
        f"- Globals referenced: {len(by_variable)} *(calculated metric)*",
        f"- Functions touching globals: {len(functions_touching)} "
        "*(calculated metric)*",
        "",
        "## What this report means",
        "",
        "References to file-scope (global) variables found inside "
        "analyzed function bodies. Read and write access is not "
        "distinguished yet. It is organized one section per variable "
        "so the functions that touch a global can be read at a "
        "glance; a variable absent from the list had no usable "
        "reference inside any analyzed function body.",
        "",
        "## Value meanings",
        "",
        "- Variable: the spelling used inside a function body. "
        "Globals may repeat when several analyzed scopes saw them.",
        "- Seen at: the file where the parser located the global. "
        "This is often a declaration in a header rather than the "
        "defining `static`/file-scope row, because the conservative "
        "parser records what it saw. `not parsed` when no matching "
        "symbol was extracted.",
        "- Reference: the enclosing function and the "
        "repository-relative file containing it.",
        "- Machine counterpart: `global_usage.json` keeps one flat "
        "entry per usage; the grouping here is presentation only.",
        "",
    ]
    if not data.entries:
        lines.append(
            "_No recorded global-variable usages. Run "
            "`cintel analyze` first. (unavailable information)_"
        )
    else:
        lines.append("## Globals")
        lines.append("")
        for variable in sorted(by_variable):
            references = sorted(
                by_variable[variable],
                key=lambda item: (item.function_path, item.function),
            )
            lines.extend((f"### `{variable}`", ""))
            seen_at = sorted(
                {
                    entry.variable_path
                    for entry in references
                    if entry.variable_path is not None
                }
            )
            if seen_at:
                lines.append(
                    "- Seen at: " + "; ".join(f"`{escape(path)}`" for path in seen_at)
                )
            else:
                lines.append("- Seen at: not parsed")
            lines.append("")
            lines.append("Referenced by:")
            lines.extend(
                f"- `{escape(item.function)}` "
                f"(`{escape(item.function_path)}`)"
                for item in references
            )
            lines.append("")
    return "\n".join(lines)
