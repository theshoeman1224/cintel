"""Markdown rendering for the repository_inventory report family.

Rendered from the typed report data assembled by
``cintel.application.reports``; the JSON sibling lives in
``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from collections import Counter

from cintel.adapters.reports.markdown.shared import (
    build_awareness_markdown,
    escape,
    require,
)
from cintel.domain.models import (
    FileKind,
    RepositoryReportData,
    RepositoryScan,
)


def render(data: RepositoryReportData) -> str:
    require(data, RepositoryReportData, "repository_inventory")
    scan = data.scan
    counts = Counter(item.kind for item in scan.files)
    lines = _preamble(scan)
    lines.extend(_capability_lines(scan))
    lines.extend(_inventory_summary(counts))
    lines.extend(_files_by_directory(scan))
    lines.extend(_files_table(scan))
    lines.extend(_diagnostics(scan))
    lines.extend(("", build_awareness_markdown(data)))
    return "\n".join(lines)


def _preamble(scan: RepositoryScan) -> list[str]:
    return [
        "# Repository Inventory",
        "",
        f"- Repository: `{scan.repository.root}`",
        f"- Scanned at: `{scan.scanned_at.isoformat()}`",
        f"- Files recorded: {len(scan.files)} *(calculated metric)*",
        f"- SHA-256 hashes computed: {scan.hashes_computed} *(calculated metric)*",
        f"- SHA-256 hashes reused: {scan.hashes_reused} *(calculated metric)*",
        "",
        "## What this report means",
        "",
        "This inventory is the scanner's snapshot of the repository: "
        "every relevant C source, header, and Make input found on disk, "
        "the per-file evidence recorded at scan time, the capabilities "
        "cintel claims, and a build-state summary from persisted build "
        "discoveries. `cintel scan` refreshes it incrementally; `cintel "
        "report` regenerates it from stored state.",
        "",
        "## Value meanings",
        "",
        "- *calculated metric*: derived from recorded rows, not a "
        "scanned field.",
        "- Evidence `extracted fact`: the value existed on disk as "
        "recorded at scan time; `unavailable information` marks facts "
        "that cannot be claimed.",
        "- Kind `c_source`/`c_header`: relevant C files; "
        "`makefile`/`make_fragment`: Make build inputs recognized by "
        "name; `other`: other recorded build-adjacent inputs.",
        "- SHA-256: content hash of the file at scan time; the "
        "`Files` table shows a 12-character short form, and "
        "`repository.json` records the full hash.",
        "- Capability status `available`/`degraded`/`unavailable` "
        "states what cintel can and cannot claim for this repository.",
        "",
        "## Capabilities and limitations",
        "",
    ]


def _capability_lines(scan: RepositoryScan) -> list[str]:
    lines: list[str] = []
    for capability in scan.capabilities:
        classification = (
            "unavailable information"
            if capability.status.value == "unavailable"
            else "extracted fact"
        )
        lines.append(
            f"- **{capability.name}** — {capability.status.value}: "
            f"{capability.reason} *({classification})*"
        )
    return lines


def _inventory_summary(counts: Counter) -> list[str]:
    lines = ["", "## Inventory summary", ""]
    for kind in FileKind:
        lines.append(
            f"- {kind.value}: {counts.get(kind, 0)} *(calculated metric)*"
        )
    return lines


def _files_by_directory(scan: RepositoryScan) -> list[str]:
    lines = ["", "## Files by top-level directory", ""]
    if not scan.files:
        lines.append(
            "_No relevant files were available. (unavailable information)_"
        )
        return lines
    counts_by_root: dict[str, int] = {}
    for item in scan.files:
        parts = item.relative_path.split("/", 1)
        key = parts[0] if len(parts) > 1 else "(root)"
        counts_by_root[key] = counts_by_root.get(key, 0) + 1
    for root in sorted(counts_by_root):
        lines.append(
            f"- `{escape(root)}`: {counts_by_root[root]} "
            "*(calculated metric)*"
        )
    return lines


def _files_table(scan: RepositoryScan) -> list[str]:
    lines = ["", "## Files", ""]
    if not scan.files:
        lines.append("_No relevant files were available. (unavailable information)_")
        return lines
    lines.append("| Path | Kind | Bytes | SHA-256 (short) | Evidence |")
    lines.append("|---|---:|---:|---|---|")
    for item in scan.files:
        lines.append(
            f"| `{escape(item.relative_path)}` | {item.kind.value} | "
            f"{item.size} | `{item.content_sha256[:12]}` | extracted fact |"
        )
    return lines


def _diagnostics(scan: RepositoryScan) -> list[str]:
    lines = ["", "## Diagnostics", ""]
    if not scan.diagnostics:
        lines.append("No scan diagnostics.")
    for diagnostic in scan.diagnostics:
        lines.append(
            f"- **{diagnostic.code}** ({diagnostic.severity.value}): "
            f"{diagnostic.message}"
        )
        if diagnostic.technical_details:
            lines.append(f"  - Details: {diagnostic.technical_details}")
        for action in diagnostic.suggested_actions:
            lines.append(f"  - Suggested action: {action}")
    return lines
