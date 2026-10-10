"""Markdown rendering for the call_graph report family.

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
    CallGraphEdge,
    CallGraphReportData,
)


def render(data: CallGraphReportData) -> str:
    require(data, CallGraphReportData, "call_graph")
    resolved = tuple(
        edge for edge in data.edges
        if edge.resolution == "confirmed_direct"
    )
    unresolved = tuple(
        edge for edge in data.edges
        if edge.resolution != "confirmed_direct"
    )
    lines = [
        "# Call Graph",
        "",
        f"- Direct-call edges: {len(data.edges)} *(calculated metric)*",
        f"- Unresolved edges: {data.unresolved_count} "
        "*(calculated metric)*",
        "",
        "## What this report means",
        "",
        "Direct calls extracted from analyzed function bodies and "
        "resolved deterministically: same-file `static` definitions "
        "win, then a single repository-wide definition, with callers "
        "using a build restricted to that build's files. It is "
        "organized one section per calling function so a "
        "function's callees read top-down; unresolved calls are "
        "listed separately, grouped by callee. Entry-point "
        "reachability and recursion findings derive from these edges.",
        "",
        "## Value meanings",
        "",
        "- Caller heading: the calling function and its defining "
        "file.",
        "- Callee: the called function with its definition location "
        "when the call resolved to one definition.",
        "- Call site: 1-based line of the calling expression.",
        "- Resolution `confirmed_direct`: exactly one definition "
        "within scope addressed the call.",
        "- Resolution `unresolved`: ambiguous (competing "
        "definitions), out of the analyzed set, or reached through "
        "machinery the conservative parser does not interpret "
        "(function pointers, macro-generated code). Unresolved "
        "edges are expected limits, not errors; grouping them by "
        "callee shows which names need external evidence.",
        "",
    ]
    if not data.edges:
        lines.extend(
            (
                "## Calls by caller",
                "",
                "_No resolved direct calls. Run `cintel analyze` "
                "first. (unavailable information)_",
                "",
            )
        )
    else:
        by_caller: dict[tuple[str, str], list[CallGraphEdge]] = {}
        for edge in resolved:
            by_caller.setdefault(
                (edge.caller_path, edge.caller), []
            ).append(edge)
        lines.extend(("## Calls by caller", ""))
        if not resolved:
            lines.append("_No calls resolved to a definition in the "
                         "analyzed scope. (unavailable information)_")
            lines.append("")
        for caller_path, caller in sorted(by_caller):
            edges = sorted(
                by_caller[(caller_path, caller)],
                key=lambda item: (item.call_site_line, item.callee),
            )
            heading = caller or "(unresolved caller)"
            lines.extend((f"### {heading} (`{escape(caller_path)}`)", ""))
            lines.append("Callees:")
            for edge in edges:
                callee = f"`{edge.callee}`"
                if edge.callee_path is not None:
                    callee += (
                        f" (`{escape(edge.callee_path)}:"
                        f"{edge.callee_line}`)"
                    )
                lines.append(
                    f"- {callee} — call site {edge.call_site_line}"
                )
            lines.append("")
        lines.append("## Unresolved calls")
        lines.append("")
        if not unresolved:
            lines.append("No unresolved direct calls.")
            lines.append("")
        else:
            by_callee: dict[str, list[CallGraphEdge]] = {}
            for edge in unresolved:
                by_callee.setdefault(edge.callee, []).append(edge)
            for callee in sorted(by_callee):
                references = sorted(
                    by_callee[callee],
                    key=lambda item: (
                        item.caller_path,
                        item.caller,
                        item.call_site_line,
                    ),
                )
                heading = callee or "(unknown callee spelling)"
                lines.extend(
                    (
                        f"### `{heading}` "
                        f"({len(references)} call sites)",
                        "",
                    )
                )
                lines.append("Called from:")
                for edge in references:
                    caller = edge.caller or "(unresolved caller)"
                    caller_text = (
                        f"`{escape(caller)}` "
                        f"(`{escape(edge.caller_path)}`"
                        f":{edge.call_site_line})"
                    )
                    lines.append(f"- {caller_text}")
                lines.append("")
    return "\n".join(lines)
