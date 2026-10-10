"""Markdown rendering for the build_selection report family.

Rendered from the typed report data assembled by
``cintel.application.reports``; the JSON sibling lives in
``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from cintel.adapters.reports.markdown.shared import (
    require,
)
from cintel.domain.models import (
    BuildSelectionReportData,
)


def render(data: BuildSelectionReportData) -> str:
    require(data, BuildSelectionReportData, "build_selection")
    selected_by_configuration = {
        entry.configuration: set(entry.selected) for entry in data.entries
    }
    lines = [
        "# Build Selection",
        "",
        "## What this report means",
        "",
        "Per persisted build configuration, the repository C sources "
        "and headers that the recorded Make commands actually compile "
        "into that build, and which scanned C files the build leaves "
        "out. It answers \"what does this build contain?\" before any "
        "source analysis is run, and each section classifies its "
        "files against the other recorded configurations so "
        "per-platform differences are visible without manual "
        "diffing.",
        "",
        "## Value meanings",
        "",
        "- Selected: files referenced as compile inputs by this "
        "configuration; they receive its exact compiler flags.",
        "- Shared / only-here roll-ins: among the Selected list, "
        "whether a file is selected by other configurations too. "
        "With a single configuration, every selection reads as "
        "only-here.",
        "- Excluded C sources and headers: present in the repository "
        "but not compiled by this build. The roll-in separates "
        "files another configuration still selects from files no "
        "recorded build compiles.",
        "- Counts are *calculated metrics* derived from the lists "
        "below.",
        "",
    ]
    if not data.entries:
        lines.append(
            "_No persisted build configurations. Run `cintel build "
            "discover` first. (unavailable information)_"
        )
    for entry in data.entries:
        others = {
            configuration: selected
            for configuration, selected in selected_by_configuration.items()
            if configuration != entry.configuration
        }
        other_selected = set().union(*others.values()) if others else set()
        shared = {
            path for path in entry.selected if path in other_selected
        }
        only_here = set(entry.selected) - shared
        excluded_but_selected_elsewhere = {
            path for path in entry.excluded if path in other_selected
        }
        excluded_everywhere = set(entry.excluded) - (
            excluded_but_selected_elsewhere
        )
        lines.extend(
            (
                f"## {entry.configuration}",
                "",
                f"- Selected sources: {len(entry.selected)} "
                "*(calculated metric)*",
                f"- Only in this configuration: {len(only_here)}; "
                f"shared with other configurations: {len(shared)} "
                "*(calculated metric)*",
                f"- Excluded C sources and headers: {len(entry.excluded)} "
                "*(calculated metric)*",
                f"- Excluded here, selected elsewhere: "
                f"{len(excluded_but_selected_elsewhere)}; compiled by "
                f"no recorded configuration: {len(excluded_everywhere)} "
                "*(calculated metric)*",
                "",
            )
        )
        if entry.selected:
            lines.append("Selected:")
            lines.extend(f"- `{path}`" for path in entry.selected)
            lines.append("")
        if entry.excluded:
            lines.append("Excluded:")
            lines.extend(f"- `{path}`" for path in entry.excluded)
            lines.append("")
    return "\n".join(lines)
