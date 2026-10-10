"""Helpers shared by the Markdown report family modules."""

from __future__ import annotations

from typing import Any

from cintel.domain.models import RepositoryReportData


def require(data: Any, expected_type: type, report_name: str) -> None:
    if not isinstance(data, expected_type):
        raise TypeError(
            f"{report_name} requires {expected_type.__name__} data"
        )



def escape(value: str) -> str:
    return value.replace("|", "\\|")



def build_awareness_markdown(data: RepositoryReportData) -> str:
    if not data.build_configurations:
        return "\n".join(
            (
                "## Build-awareness status",
                "",
                "No persisted build discoveries are recorded for this "
                "repository yet, so this inventory cannot report build "
                "membership. Run `cintel build discover` to record build "
                "configurations, per-file compiler flags, and exact compiler "
                "arguments. *(unavailable information)*",
                "",
            )
        )
    lines = [
        "## Build-awareness status",
        "",
        f"- Persisted build configurations: "
        f"{len(data.build_configurations)} *(calculated metric)*",
        f"- Compilation units recorded: {data.compilation_unit_count} "
        "*(calculated metric)*",
        f"- Files with analysis results: {data.analyzed_file_count} "
        "*(calculated metric)*",
        "",
        "Persisted build discoveries are integrated below and in the "
        "`build_selection` and `compilation_units` reports.",
        "",
        "## Build configurations",
        "",
    ]
    for configuration in data.build_configurations:
        lines.append(f"- {configuration.name} (target: `{configuration.target or 'default'}`)")
    lines.append("")
    return "\n".join(lines)
