"""Markdown rendering for the capability_index report family.

Rendered from the typed report data assembled by
``cintel.application.reports``; the JSON sibling lives in
``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from cintel.adapters.reports.markdown.shared import (
    require,
)
from cintel.domain.models import (
    CapabilityIndexReportData,
)


def render(data: CapabilityIndexReportData) -> str:
    require(data, CapabilityIndexReportData, "capability_index")
    lines = [
        "# Capability Index",
        "",
        f"- Capability records: {len(data.entries)} "
        "*(calculated metric)*",
        "",
        "## What this report means",
        "",
        "What cintel can honestly claim it can do for this repository "
        "in its current environment: which features are available, "
        "which are limited, and which could not be reached at all. "
        "Tool availability, build discovery, and analysis scope all "
        "appear here.",
        "",
        "## Value meanings",
        "",
        "- Status `available`: working without restrictions; "
        "`degraded`: works with explicit limitations; `unavailable`: "
        "not claimed in this run.",
        "- Reason: why the status holds; Evidence: concrete values "
        "supporting it.",
        "- Classification `extracted fact` vs `unavailable information` "
        "mirrors the evidence policy used across all reports.",
        "",
    ]
    if not data.entries:
        lines.append("No capability records recorded.")
    else:
        status_rank = {"unavailable": 0, "degraded": 1, "available": 2}
        ordered = sorted(
            data.entries,
            key=lambda item: (
                status_rank.get(item.status.value, 3),
                item.name,
            ),
        )
        for item in ordered:
            classification = (
                "unavailable information"
                if item.status.value == "unavailable"
                else "extracted fact"
            )
            lines.append(
                f"- **{item.name}** — {item.status.value}: {item.reason} "
                f"*({classification})*"
            )
            for evidence in item.evidence:
                lines.append(f"  - Evidence: {evidence}")
    return "\n".join(lines)
