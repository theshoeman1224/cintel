"""Markdown rendering for the compilation_units report family.

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
    CompilationUnitEntry,
    CompilationUnitsReportData,
)


def render(data: CompilationUnitsReportData) -> str:
    require(data, CompilationUnitsReportData, "compilation_units")
    lines = [
        "# Compilation Units",
        "",
        f"- Units recorded: {len(data.entries)} *(calculated metric)*",
        "",
        "## What this report means",
        "",
        "One row per persisted compilation unit — a single source file "
        "compiled under a single build configuration with an exact set "
        "of compiler arguments. It is organized one section per build "
        "configuration, matching `build_selection.md`, so the units of "
        "one build read together. Source analysis keys reanalysis on a "
        "unit's fingerprint, so this list defines how source files map "
        "to compiler configurations.",
        "",
        "## Value meanings",
        "",
        "- Unit: first characters of the stable identifier derived "
        "from the normalized command and build inputs; the same "
        "source may appear under several configurations.",
        "- Configuration: the named build configuration heading each "
        "section.",
        "- Source: the `.c` file being compiled; `—` when the compiler "
        "command references a file that is not (or no longer) in the "
        "repository scan.",
        "- Compiler: the recognized compiler executable; launcher or "
        "wrapper tokens are recorded in storage, not shown here.",
        "- Defines: count of `-D`/`-U` arguments; Include paths: count "
        "of `-I`/`-isystem` arguments.",
        "",
    ]
    if not data.entries:
        lines.append(
            "_No compilation units. Run `cintel build discover` first. "
            "(unavailable information)_"
        )
    else:
        by_configuration: dict[str, list[CompilationUnitEntry]] = {}
        for entry in data.entries:
            by_configuration.setdefault(entry.configuration, []).append(
                entry
            )
        for configuration in sorted(by_configuration):
            units = sorted(
                by_configuration[configuration],
                key=lambda item: (
                    item.source_path or "",
                    item.unit_id,
                ),
            )
            lines.extend(
                (
                    f"## {configuration} ({len(units)})",
                    "",
                    "| Unit | Source | Compiler | Defines | Include paths |",
                    "|---|---|---|---:|---:|",
                )
            )
            for entry in units:
                source = entry.source_path or "—"
                lines.append(
                    f"| `{entry.unit_id[:16]}…` | `{escape(source)}` | "
                    f"{entry.compiler} | "
                    f"{entry.define_count} | {entry.include_path_count} |"
                )
            lines.append("")
    return "\n".join(lines)
