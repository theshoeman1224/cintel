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
            "- SHA-256: content hash of the file at scan time.",
            "- Capability status `available`/`degraded`/`unavailable` "
            "states what cintel can and cannot claim for this repository.",
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
        lines = [
            "# Build Selection",
            "",
            "## What this report means",
            "",
            "Per persisted build configuration, the repository C sources "
            "and headers that the recorded Make commands actually compile "
            "into that build, and which scanned C files the build leaves "
            "out. It answers \"what does this build contain?\" before any "
            "source analysis is run.",
            "",
            "## Value meanings",
            "",
            "- Selected: files referenced as compile inputs by this "
            "configuration; they receive its exact compiler flags.",
            "- Excluded C sources and headers: present in the repository "
            "but not compiled by this build (per-platform or unused "
            "sources).",
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
            "## What this report means",
            "",
            "One row per persisted compilation unit — a single source file "
            "compiled under a single build configuration with an exact set "
            "of compiler arguments. Source analysis keys reanalysis on a "
            "unit's fingerprint, so this list defines how source files map "
            "to compiler configurations.",
            "",
            "## Value meanings",
            "",
            "- Unit: first characters of the stable identifier derived "
            "from the normalized command and build inputs; the same "
            "source may appear under several configurations.",
            "- Configuration: the named build configuration the unit "
            "belongs to.",
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
            "## What this report means",
            "",
            "Functions the conservative parser extracted from analyzed "
            "source files — every declared or defined function name, where "
            "it lives, its linkage, and whether cintel saw a full "
            "definition. It is the lookup table behind `cintel show "
            "function` and the context packages.",
            "",
            "## Value meanings",
            "",
            "- Function: spelling as written in the source.",
            "- State `definition`: a complete function body was parsed; "
            "`declaration`: only a prototype (signature) was seen.",
            "- Linkage: `internal` (`static`), `external` (default), or "
            "`unknown` when the parser could not decide.",
            "- Location: repository-relative path and 1-based line of the "
            "definition or declaration.",
            "- Same function may appear once per analyzed scope; rows are "
            "deduplicated by source location.",
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
            "## What this report means",
            "",
            "Direct calls extracted from analyzed function bodies and "
            "resolved deterministically: same-file `static` definitions "
            "win, then a single repository-wide definition, with callers "
            "using a build restricted to that build's files. Entry-point "
            "reachability and recursion findings derive from these edges.",
            "",
            "## Value meanings",
            "",
            "- Caller / Callee: function spellings with their defining "
            "files in parentheses; a callee without a path has no knowable "
            "definition.",
            "- Call site: 1-based line of the calling expression.",
            "- Resolution `confirmed_direct`: exactly one definition "
            "within scope addressed the call.",
            "- Resolution `unresolved`: ambiguous (competing definitions), "
            "out of the analyzed set, or reached through machinery the "
            "conservative parser does not interpret (function pointers, "
            "macro-generated code). Unresolved edges are expected limits, "
            "not errors.",
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
            "## What this report means",
            "",
            "Every `#include` directive the conservative parser found in "
            "analyzed files, and whether it could be mapped to an actual "
            "file. Resolution uses the including file's directory plus the "
            "compilation unit's `-I` paths, so unresolved rows show which "
            "headers the analysis could not see.",
            "",
            "## Value meanings",
            "",
            "- Including file / Included: repository-relative path of the "
            "file holding the directive, its line, and the spelling "
            "exactly as written after `#include` (angle brackets and "
            "quotes included).",
            "- Resolved: the found file's repository-relative path.",
            "- Resolved `unresolved`: no matching file in the search "
            "paths — typical for system headers (`<stdio.h>`) and "
            "generated headers that do not exist yet. This is an "
            "explicitly reported limit, not an error.",
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
            "## What this report means",
            "",
            "Named things the conservative parser found while analyzing "
            "source files: functions, file-scope variables, named types, "
            "and macros. Machine-readable counterpart to `cintel symbols` "
            "and the store behind `symbol_index.json` fixture validation.",
            "",
            "## Value meanings",
            "",
            "- Kind: `function`, `variable` (file-scope objects), `type` "
            "(structs, unions, enums, typedefs, opaque types), or `macro` "
            "(`#define`).",
            "- State: `definition` (the parser saw the full body/type), "
            "`declaration` (extern prototypes, extern/forward types), "
            "`n/a` for symbols without a definition/declaration split.",
            "- Location: repository-relative path and 1-based line.",
            "- Rows are deduplicated by source location across analyzed "
            "scopes; queryable via `cintel symbols [--kind ...]`.",
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
            "## What this report means",
            "",
            "References to file-scope (global) variables found inside "
            "analyzed function bodies. Read and write access is not "
            "distinguished yet; this report shows which functions touch "
            "which globals and where the globals are defined.",
            "",
            "## Value meanings",
            "",
            "- Function / Location: enclosing function and the "
            "repository-relative file containing it.",
            "- Variable: the referenced global's spelling; the definition "
            "file path in parentheses when the parser could locate the "
            "defining row.",
            "- Usages between functions in different analyzed scopes may "
            "repeat the same variable.",
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
            "## What this report means",
            "",
            "Every structured diagnostic cintel recorded across workflow "
            "stages — scan, build discovery, recovery, analysis, report "
            "generation. Codes identify conditions stably so guidance, "
            "tests, and filters key on them.",
            "",
            "## Value meanings",
            "",
            "- Code (`CI-*-*`): stable condition identifiers — the "
            "`DiagnosticCode` enumeration in `cintel.domain.diagnostics` is "
            "the contract.",
            "- Severity `info`: noteworthy; `warning`: attention needed but "
            "the workflow continued; `error`: the stage could not complete "
            "as requested.",
            "- Details: technical context captured with the condition.",
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
