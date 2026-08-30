from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.domain.models import (
    BuildSelectionReportData,
    CallGraphReportData,
    CapabilityIndexReportData,
    CompilationUnitsReportData,
    DiagnosticsReportData,
    FileKind,
    FunctionIndexReportData,
    GlobalUsageReportData,
    IncludeIndexReportData,
    RepositoryReportData,
    RepositoryScan,
    SymbolIndexReportData,
)


class MarkdownReportRenderer:
    def render(self, report_name: str, data: Any) -> str:
        handler = _MARKDOWN_HANDLERS.get(report_name)
        if handler is None:
            raise ValueError(f"Unsupported report: {report_name}")
        return handler(self, data)

    def _repository_inventory(self, data: RepositoryReportData) -> str:
        _require(data, RepositoryReportData, "repository_inventory")
        scan = data.scan
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
        lines.extend(("", _build_awareness_markdown(data)))
        return "\n".join(lines)

    def _build_selection(self, data: BuildSelectionReportData) -> str:
        _require(data, BuildSelectionReportData, "build_selection")
        lines = ["# Build Selection", ""]
        if not data.entries:
            lines.append(
                "_No persisted build configurations. Run `cintel build "
                "discover` first. (unavailable information)_"
            )
        for entry in data.entries:
            lines.extend(
                (
                    f"## {entry.configuration}",
                    "",
                    f"- Selected sources: {len(entry.selected)} "
                    "*(calculated metric)*",
                    f"- Excluded C sources and headers: {len(entry.excluded)} "
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

    def _compilation_units(self, data: CompilationUnitsReportData) -> str:
        _require(data, CompilationUnitsReportData, "compilation_units")
        lines = [
            "# Compilation Units",
            "",
            f"- Units recorded: {len(data.entries)} *(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append(
                "_No compilation units. Run `cintel build discover` first. "
                "(unavailable information)_"
            )
        else:
            lines.extend(
                (
                    "| Unit | Configuration | Source | Compiler | Defines | "
                    "Include paths |",
                    "|---|---|---|---|---:|---:|",
                )
            )
            for entry in data.entries:
                source = entry.source_path or "—"
                lines.append(
                    f"| `{entry.unit_id[:16]}…` | {entry.configuration} | "
                    f"`{_escape(source)}` | {entry.compiler} | "
                    f"{entry.define_count} | {entry.include_path_count} |"
                )
        return "\n".join(lines)

    def _function_index(self, data: FunctionIndexReportData) -> str:
        _require(data, FunctionIndexReportData, "function_index")
        lines = [
            "# Function Index",
            "",
            f"- Definitions: {data.definition_count} *(calculated metric)*",
            f"- Declarations: {data.declaration_count} *(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("_No analyzed functions. Run `cintel analyze` first. "
                         "(unavailable information)_")
        else:
            lines.extend(
                ("| Function | State | Linkage | Location |", "|---|---|---|---|")
            )
            for entry in data.entries:
                state = "definition" if entry.is_definition else "declaration"
                lines.append(
                    f"| {entry.name} | {state} | {entry.linkage} | "
                    f"`{_escape(entry.relative_path)}:{entry.line}` |"
                )
        return "\n".join(lines)

    def _call_graph(self, data: CallGraphReportData) -> str:
        _require(data, CallGraphReportData, "call_graph")
        lines = [
            "# Call Graph",
            "",
            f"- Direct-call edges: {len(data.edges)} *(calculated metric)*",
            f"- Unresolved edges: {data.unresolved_count} *(calculated metric)*",
            "",
        ]
        if not data.edges:
            lines.append("_No resolved direct calls. Run `cintel analyze` "
                         "first. (unavailable information)_")
        else:
            lines.extend(
                (
                    "| Caller | Call site | Callee | Resolution |",
                    "|---|---|---|---|",
                )
            )
            for edge in data.edges:
                callee = edge.callee
                if edge.callee_path is not None:
                    callee = f"{callee} (`{_escape(edge.callee_path)}`)"
                lines.append(
                    f"| {edge.caller} (`{_escape(edge.caller_path)}`) | "
                    f"{edge.call_site_line} | {callee} | {edge.resolution} |"
                )
        return "\n".join(lines)

    def _include_index(self, data: IncludeIndexReportData) -> str:
        _require(data, IncludeIndexReportData, "include_index")
        lines = [
            "# Include Index",
            "",
            f"- Include directives: {len(data.entries)} *(calculated metric)*",
            f"- Unresolved includes: {data.unresolved_count} "
            "*(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("_No analyzed includes. Run `cintel analyze` first. "
                         "(unavailable information)_")
        else:
            lines.extend(
                ("| Including file | Line | Included | Resolved |",
                 "|---|---:|---|---|")
            )
            for entry in data.entries:
                resolved = (
                    f"`{_escape(entry.resolved_path)}`"
                    if entry.resolved_path is not None
                    else "unresolved"
                )
                lines.append(
                    f"| `{_escape(entry.including_path)}` | {entry.line} | "
                    f"`{_escape(entry.included_spelling)}` | {resolved} |"
                )
        return "\n".join(lines)

    def _symbol_index(self, data: SymbolIndexReportData) -> str:
        _require(data, SymbolIndexReportData, "symbol_index")
        lines = [
            "# Symbol Index",
            "",
            f"- Symbols recorded: {len(data.entries)} *(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("_No analyzed symbols. Run `cintel analyze` first. "
                         "(unavailable information)_")
        else:
            lines.extend(
                ("| Symbol | Kind | State | Location |", "|---|---|---|---|")
            )
            for entry in data.entries:
                state = (
                    "n/a"
                    if entry.is_definition is None
                    else ("definition" if entry.is_definition else "declaration")
                )
                lines.append(
                    f"| {entry.name} | {entry.kind} | {state} | "
                    f"`{_escape(entry.relative_path)}:{entry.line}` |"
                )
        return "\n".join(lines)

    def _global_usage(self, data: GlobalUsageReportData) -> str:
        _require(data, GlobalUsageReportData, "global_usage")
        lines = [
            "# Global Usage",
            "",
            f"- Recorded usages: {len(data.entries)} *(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("_No recorded global-variable usages. Run "
                         "`cintel analyze` first. (unavailable information)_")
        else:
            lines.extend(
                ("| Function | Location | Variable | Definition |",
                 "|---|---|---|---|")
            )
            for entry in data.entries:
                variable = entry.variable
                if entry.variable_path is not None:
                    variable = f"{variable} (`{_escape(entry.variable_path)}`)"
                lines.append(
                    f"| {entry.function} | `{_escape(entry.function_path)}` | "
                    f"{variable} | |"
                )
        return "\n".join(lines)

    def _diagnostics_index(self, data: DiagnosticsReportData) -> str:
        _require(data, DiagnosticsReportData, "diagnostics_index")
        lines = [
            "# Diagnostics Index",
            "",
            f"- Diagnostics recorded: {len(data.entries)} "
            "*(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("No diagnostics recorded.")
        for item in data.entries:
            lines.append(
                f"- **{item.code}** ({item.severity.value}): {item.message}"
            )
            if item.technical_details:
                lines.append(f"  - Details: {item.technical_details}")
        return "\n".join(lines)

    def _capability_index(self, data: CapabilityIndexReportData) -> str:
        _require(data, CapabilityIndexReportData, "capability_index")
        lines = [
            "# Capability Index",
            "",
            f"- Capability records: {len(data.entries)} "
            "*(calculated metric)*",
            "",
        ]
        if not data.entries:
            lines.append("No capability records recorded.")
        for item in data.entries:
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


class JSONReportRenderer:
    def render(self, report_name: str, data: Any) -> str:
        handler = _JSON_HANDLERS.get(report_name)
        if handler is None:
            raise ValueError(f"Unsupported report: {report_name}")
        return handler(self, data)

    def _repository_inventory(self, data: RepositoryReportData) -> str:
        _require(data, RepositoryReportData, "repository_inventory")
        scan = data.scan
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
            "build": {
                "classification": (
                    "extracted_fact"
                    if data.build_configurations
                    else "unavailable_information"
                ),
                "build_configurations": [
                    item.name for item in data.build_configurations
                ],
                "compilation_unit_count": data.compilation_unit_count,
                "analyzed_file_count": data.analyzed_file_count,
            },
        }
        return json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"

    def _build_selection(self, data: BuildSelectionReportData) -> str:
        _require(data, BuildSelectionReportData, "build_selection")
        payload = {
            "report": "build_selection",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _compilation_units(self, data: CompilationUnitsReportData) -> str:
        _require(data, CompilationUnitsReportData, "compilation_units")
        payload = {
            "report": "compilation_units",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _function_index(self, data: FunctionIndexReportData) -> str:
        _require(data, FunctionIndexReportData, "function_index")
        payload = {
            "report": "function_index",
            "definition_count": data.definition_count,
            "declaration_count": data.declaration_count,
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _call_graph(self, data: CallGraphReportData) -> str:
        _require(data, CallGraphReportData, "call_graph")
        payload = {
            "report": "call_graph",
            "unresolved_count": data.unresolved_count,
            "edges": [asdict(item) for item in data.edges],
        }
        return _dump(payload)

    def _include_index(self, data: IncludeIndexReportData) -> str:
        _require(data, IncludeIndexReportData, "include_index")
        payload = {
            "report": "include_index",
            "unresolved_count": data.unresolved_count,
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _symbol_index(self, data: SymbolIndexReportData) -> str:
        _require(data, SymbolIndexReportData, "symbol_index")
        payload = {
            "report": "symbol_index",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _global_usage(self, data: GlobalUsageReportData) -> str:
        _require(data, GlobalUsageReportData, "global_usage")
        payload = {
            "report": "global_usage",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _diagnostics_index(self, data: DiagnosticsReportData) -> str:
        _require(data, DiagnosticsReportData, "diagnostics_index")
        payload = {
            "report": "diagnostics_index",
            "entries": [
                {**asdict(item), "severity": item.severity.value}
                for item in data.entries
            ],
        }
        return _dump(payload)

    def _capability_index(self, data: CapabilityIndexReportData) -> str:
        _require(data, CapabilityIndexReportData, "capability_index")
        payload = {
            "report": "capability_index",
            "entries": [
                {**asdict(item), "status": item.status.value}
                for item in data.entries
            ],
        }
        return _dump(payload)


def _build_awareness_markdown(data: RepositoryReportData) -> str:
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


_MARKDOWN_HANDLERS = {
    "repository_inventory": MarkdownReportRenderer._repository_inventory,
    "symbol_index": MarkdownReportRenderer._symbol_index,
    "global_usage": MarkdownReportRenderer._global_usage,
    "build_selection": MarkdownReportRenderer._build_selection,
    "compilation_units": MarkdownReportRenderer._compilation_units,
    "function_index": MarkdownReportRenderer._function_index,
    "call_graph": MarkdownReportRenderer._call_graph,
    "include_index": MarkdownReportRenderer._include_index,
    "diagnostics_index": MarkdownReportRenderer._diagnostics_index,
    "capability_index": MarkdownReportRenderer._capability_index,
}

_JSON_HANDLERS = {
    "repository_inventory": JSONReportRenderer._repository_inventory,
    "symbol_index": JSONReportRenderer._symbol_index,
    "global_usage": JSONReportRenderer._global_usage,
    "build_selection": JSONReportRenderer._build_selection,
    "compilation_units": JSONReportRenderer._compilation_units,
    "function_index": JSONReportRenderer._function_index,
    "call_graph": JSONReportRenderer._call_graph,
    "include_index": JSONReportRenderer._include_index,
    "diagnostics_index": JSONReportRenderer._diagnostics_index,
    "capability_index": JSONReportRenderer._capability_index,
}


def _require(data: Any, expected_type: type, report_name: str) -> None:
    if not isinstance(data, expected_type):
        raise TypeError(
            f"{report_name} requires {expected_type.__name__} data"
        )


def _dump(payload: dict) -> str:
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"


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
