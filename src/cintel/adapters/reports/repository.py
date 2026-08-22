from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.domain.models import FileKind, RepositoryScan


class MarkdownReportRenderer:
    def render(self, report_name: str, data: Any) -> str:
        scan = _require_repository_scan(report_name, data)
        counts = Counter(item.kind for item in scan.files)
        lines = [
            "# Repository Inventory",
            "",
            f"- Repository: `{scan.repository.root}`",
            f"- Scanned at: `{scan.scanned_at.isoformat()}`",
            f"- Files recorded: {len(scan.files)} *(calculated metric)*",
            f"- SHA-256 hashes computed: {scan.hashes_computed} *(calculated metric)*",
            f"- SHA-256 hashes reused: {scan.hashes_reused} *(calculated metric)*",
            "",
            "## Capabilities and limitations",
            "",
        ]
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
        lines.extend(("", "## Inventory summary", ""))
        for kind in FileKind:
            lines.append(
                f"- {kind.value}: {counts.get(kind, 0)} *(calculated metric)*"
            )
        lines.extend(("", "## Files", ""))
        if not scan.files:
            lines.append("_No relevant files were available. (unavailable information)_")
        else:
            lines.append("| Path | Kind | Bytes | SHA-256 | Evidence |")
            lines.append("|---|---:|---:|---|---|")
            for item in scan.files:
                lines.append(
                    f"| `{_escape(item.relative_path)}` | {item.kind.value} | "
                    f"{item.size} | `{item.content_sha256}` | extracted fact |"
                )
        lines.extend(("", "## Diagnostics", ""))
        if not scan.diagnostics:
            lines.append("No scan diagnostics.")
        for item in scan.diagnostics:
            lines.append(
                f"- **{item.code}** ({item.severity.value}): {item.message}"
            )
            if item.technical_details:
                lines.append(f"  - Details: {item.technical_details}")
            for action in item.suggested_actions:
                lines.append(f"  - Suggested action: {action}")
        lines.extend(
            (
                "",
                "## Build-awareness status",
                "",
                "This report reflects repository scanning only and does not "
                "include persisted build discoveries. Run `cintel build "
                "discover` for build-target membership, per-file compiler "
                "flags, and exact compiler arguments. *(unavailable "
                "information)*",
                "",
            )
        )
        return "\n".join(lines)


class JSONReportRenderer:
    def render(self, report_name: str, data: Any) -> str:
        scan = _require_repository_scan(report_name, data)
        counts = Counter(item.kind.value for item in scan.files)
        payload = {
            "report": "repository_inventory",
            "repository": {
                "id": scan.repository.id,
                "root": scan.repository.root,
                "name": scan.repository.name,
                "classification": "extracted_fact",
            },
            "scanned_at": scan.scanned_at.isoformat(),
            "metrics": {
                "classification": "calculated_metric",
                "files_recorded": len(scan.files),
                "hashes_computed": scan.hashes_computed,
                "hashes_reused": scan.hashes_reused,
                "files_by_kind": dict(sorted(counts.items())),
            },
            "files": [
                {
                    **asdict(item),
                    "kind": item.kind.value,
                    "modified_at": item.modified_at.isoformat(),
                    "classification": "extracted_fact",
                }
                for item in scan.files
            ],
            "capabilities": [
                {
                    "name": item.name,
                    "status": item.status.value,
                    "reason": item.reason,
                    "evidence": item.evidence,
                    "classification": (
                        "unavailable_information"
                        if item.status.value == "unavailable"
                        else "extracted_fact"
                    ),
                }
                for item in scan.capabilities
            ],
            "diagnostics": [asdict(item) for item in scan.diagnostics],
        }
        return json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"


def _require_repository_scan(report_name: str, data: Any) -> RepositoryScan:
    if report_name != "repository_inventory":
        raise ValueError(f"Unsupported report: {report_name}")
    if not isinstance(data, RepositoryScan):
        raise TypeError("repository_inventory requires RepositoryScan data")
    return data


def _escape(value: str) -> str:
    return value.replace("|", "\\|")


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")
