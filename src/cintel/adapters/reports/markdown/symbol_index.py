"""Markdown rendering for the symbol_index report family.

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
    SymbolIndexEntry,
    SymbolIndexReportData,
)


def render(data: SymbolIndexReportData) -> str:
    require(data, SymbolIndexReportData, "symbol_index")
    by_kind: dict[str, list[SymbolIndexEntry]] = {}
    for entry in data.entries:
        by_kind.setdefault(entry.kind, []).append(entry)
    lines = [
        "# Symbol Index",
        "",
        f"- Symbols recorded: {len(data.entries)} *(calculated metric)*",
        "",
        "## What this report means",
        "",
        "Named things the conservative parser found while analyzing "
        "source files: functions, file-scope variables, named types, "
        "and macros. It is organized one section per kind with "
        "symbols alphabetized by name, so a symbol lookup needs no "
        "scanning; `symbol_index.json` keeps location order for "
        "machine consumption. This is the lookup table behind "
        "`cintel symbols` and the store behind `symbol_index.json` "
        "fixture validation.",
        "",
        "## Value meanings",
        "",
        "- Sections: `function`, `variable` (file-scope objects), "
        "`type` (structs, unions, enums, typedefs, opaque types), "
        "`macro` (`#define`).",
        "- State: `definition` (the parser saw the full body/type), "
        "`declaration` (extern prototypes, extern/forward types), "
        "`n/a` for symbols without a definition/declaration split.",
        "- Location: repository-relative path and 1-based line.",
        "- Rows are deduplicated by source location across analyzed "
        "scopes; queryable via `cintel symbols [--kind ...]`.",
        "",
    ]
    if not data.entries:
        lines.append("_No analyzed symbols. Run `cintel analyze` first. "
                     "(unavailable information)_")
    else:
        for kind in sorted(by_kind):
            entries = sorted(
                by_kind[kind],
                key=lambda item: (item.name, item.relative_path, item.line),
            )
            lines.extend(
                (
                    f"## {kind.capitalize()}s ({len(entries)})",
                    "",
                    "| Symbol | State | Location |",
                    "|---|---|---|",
                )
            )
            for entry in entries:
                state = (
                    "n/a"
                    if entry.is_definition is None
                    else ("definition" if entry.is_definition else "declaration")
                )
                lines.append(
                    f"| {entry.name} | {state} | "
                    f"`{escape(entry.relative_path)}:{entry.line}` |"
                )
            lines.append("")
    return "\n".join(lines)
