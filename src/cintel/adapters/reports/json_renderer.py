"""JSON report renderer.

Each family serializes its typed report data with ``asdict`` so the output
shape follows the domain models. Markdown siblings live in
``cintel.adapters.reports.markdown``.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.adapters.reports.markdown.shared import require
from cintel.domain.models import (
    BuildSelectionReportData,
    CallGraphReportData,
    CapabilityIndexReportData,
    CompilationUnitsReportData,
    DiagnosticsReportData,
    FunctionIndexReportData,
    GlobalUsageReportData,
    IncludeIndexReportData,
    RepositoryReportData,
    SymbolIndexReportData,
)


class JSONReportRenderer:
    def render(self, report_name: str, data: Any) -> str:
        handler = _JSON_HANDLERS.get(report_name)
        if handler is None:
            raise ValueError(f"Unsupported report: {report_name}")
        return handler(self, data)

    def _repository_inventory(self, data: RepositoryReportData) -> str:
        require(data, RepositoryReportData, "repository_inventory")
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
        require(data, BuildSelectionReportData, "build_selection")
        payload = {
            "report": "build_selection",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _compilation_units(self, data: CompilationUnitsReportData) -> str:
        require(data, CompilationUnitsReportData, "compilation_units")
        payload = {
            "report": "compilation_units",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _function_index(self, data: FunctionIndexReportData) -> str:
        require(data, FunctionIndexReportData, "function_index")
        payload = {
            "report": "function_index",
            "definition_count": data.definition_count,
            "declaration_count": data.declaration_count,
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _call_graph(self, data: CallGraphReportData) -> str:
        require(data, CallGraphReportData, "call_graph")
        payload = {
            "report": "call_graph",
            "unresolved_count": data.unresolved_count,
            "edges": [asdict(item) for item in data.edges],
        }
        return _dump(payload)

    def _include_index(self, data: IncludeIndexReportData) -> str:
        require(data, IncludeIndexReportData, "include_index")
        payload = {
            "report": "include_index",
            "unresolved_count": data.unresolved_count,
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _symbol_index(self, data: SymbolIndexReportData) -> str:
        require(data, SymbolIndexReportData, "symbol_index")
        payload = {
            "report": "symbol_index",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _global_usage(self, data: GlobalUsageReportData) -> str:
        require(data, GlobalUsageReportData, "global_usage")
        payload = {
            "report": "global_usage",
            "entries": [asdict(item) for item in data.entries],
        }
        return _dump(payload)

    def _diagnostics_index(self, data: DiagnosticsReportData) -> str:
        require(data, DiagnosticsReportData, "diagnostics_index")
        payload = {
            "report": "diagnostics_index",
            "entries": [
                {**asdict(item), "severity": item.severity.value}
                for item in data.entries
            ],
        }
        return _dump(payload)

    def _capability_index(self, data: CapabilityIndexReportData) -> str:
        require(data, CapabilityIndexReportData, "capability_index")
        payload = {
            "report": "capability_index",
            "entries": [
                {**asdict(item), "status": item.status.value}
                for item in data.entries
            ],
        }
        return _dump(payload)

_JSON_HANDLERS: dict[str, Callable[[JSONReportRenderer, Any], str]] = {
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


def _dump(payload: dict) -> str:
    return json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")
