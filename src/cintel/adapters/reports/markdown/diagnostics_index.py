"""Markdown rendering for the diagnostics_index report family.

Rendered from the typed report data assembled by
``cintel.application.reports``; the JSON sibling lives in
``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from cintel.adapters.reports.markdown.shared import (
    require,
)
from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    DiagnosticsReportData,
)


def render(data: DiagnosticsReportData) -> str:
    require(data, DiagnosticsReportData, "diagnostics_index")
    by_code: dict[str, list[Diagnostic]] = {}
    for item in data.entries:
        by_code.setdefault(item.code, []).append(item)
    lines = [
        "# Diagnostics Index",
        "",
        f"- Diagnostics recorded: {len(data.entries)} "
        "*(calculated metric)*",
        f"- Codes in this list: {len(by_code)} *(calculated metric)*",
        "",
        "## What this report means",
        "",
        "Every structured diagnostic cintel recorded across workflow "
        "stages — scan, build discovery, recovery, analysis, report "
        "generation. It is organized one section per diagnostic code "
        "so every occurrence of one condition is read together; "
        "`diagnostics_index.json` keeps flat records. Codes identify "
        "conditions stably so guidance, tests, and filters key on "
        "them.",
        "",
        "## Value meanings",
        "",
        "- Section heading (code, `CI-*-*`): stable condition "
        "identifier — the `DiagnosticCode` enumeration in "
        "`cintel.domain.diagnostics` is the contract.",
        "- Severity `info`: noteworthy; `warning`: attention needed "
        "but the workflow continued; `error`: the stage could not "
        "complete as requested. Errors are listed first within a "
        "code section.",
        "- Details: technical context captured with the condition.",
        "",
    ]
    if not data.entries:
        lines.append("No diagnostics recorded.")
    else:
        severity_rank = {"error": 0, "warning": 1, "info": 2}
        for code in sorted(by_code):
            entries = sorted(
                by_code[code],
                key=lambda item: (
                    severity_rank.get(item.severity.value, 3),
                    item.message,
                    item.technical_details or "",
                ),
            )
            lines.extend((f"## {code} ({len(entries)})", ""))
            for item in entries:
                lines.append(
                    f"- *({item.severity.value})* {item.message}"
                )
                if item.technical_details:
                    lines.append(f"  - Details: {item.technical_details}")
            lines.append("")
    return "\n".join(lines)
