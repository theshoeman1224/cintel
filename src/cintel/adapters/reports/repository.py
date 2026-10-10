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
    GlobalUsageIndexEntry,
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
            "- SHA-256: content hash of the file at scan time; the "
            "`Files` table shows a 12-character short form, and "
            "`repository.json` records the full hash.",
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
        lines.extend(("", "## Files by top-level directory", ""))
        if not scan.files:
            lines.append(
                "_No relevant files were available. (unavailable information)_"
            )
        else:
            counts_by_root: dict[str, int] = {}
            for item in scan.files:
                parts = item.relative_path.split("/", 1)
                key = parts[0] if len(parts) > 1 else "(root)"
                counts_by_root[key] = counts_by_root.get(key, 0) + 1
            for root in sorted(counts_by_root):
                lines.append(
                    f"- `{_escape(root)}`: {counts_by_root[root]} "
                    "*(calculated metric)*"
                )
        lines.extend(("", "## Files", ""))
        if not scan.files:
            lines.append("_No relevant files were available. (unavailable information)_")
        else:
            lines.append("| Path | Kind | Bytes | SHA-256 (short) | Evidence |")
            lines.append("|---|---:|---:|---|---|")
            for item in scan.files:
                lines.append(
                    f"| `{_escape(item.relative_path)}` | {item.kind.value} | "
                    f"{item.size} | `{item.content_sha256[:12]}` | extracted fact |"
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
                        f"| `{entry.unit_id[:16]}…` | `{_escape(source)}` | "
                        f"{entry.compiler} | "
                        f"{entry.define_count} | {entry.include_path_count} |"
                    )
                lines.append("")
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
            "definition. It is organized one heading per file so a file's "
            "functions are read top-down without consulting the "
            "scanner's file list; a flat, file-ordered view remains in "
            "`function_index.json`. It is the lookup table behind "
            "`cintel show function` and the context packages.",
            "",
            "## Value meanings",
            "",
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
            by_file: dict[str, list[FunctionIndexEntry]] = {}
            for entry in data.entries:
                by_file.setdefault(entry.relative_path, []).append(entry)
            for relative_path in sorted(by_file):
                entries = sorted(
                    by_file[relative_path],
                    key=lambda item: (item.line, item.name),
                )
                lines.extend(
                    (f"## `{_escape(relative_path)}`", "")
                )
                for entry in entries:
                    state = "definition" if entry.is_definition else "declaration"
                    lines.append(
                        f"- {entry.name} — {state}, {entry.linkage}, "
                        f"`{_escape(entry.relative_path)}:{entry.line}`"
                    )
                lines.append("")
        return "\n".join(lines)

    def _call_graph(self, data: CallGraphReportData) -> str:
        _require(data, CallGraphReportData, "call_graph")
        resolved = tuple(
            edge for edge in data.edges
            if edge.resolution == "confirmed_direct"
        )
        unresolved = tuple(
            edge for edge in data.edges
            if edge.resolution != "confirmed_direct"
        )
        lines = [
            "# Call Graph",
            "",
            f"- Direct-call edges: {len(data.edges)} *(calculated metric)*",
            f"- Unresolved edges: {data.unresolved_count} "
            "*(calculated metric)*",
            "",
            "## What this report means",
            "",
            "Direct calls extracted from analyzed function bodies and "
            "resolved deterministically: same-file `static` definitions "
            "win, then a single repository-wide definition, with callers "
            "using a build restricted to that build's files. It is "
            "organized one section per calling function so a "
            "function's callees read top-down; unresolved calls are "
            "listed separately, grouped by callee. Entry-point "
            "reachability and recursion findings derive from these edges.",
            "",
            "## Value meanings",
            "",
            "- Caller heading: the calling function and its defining "
            "file.",
            "- Callee: the called function with its definition location "
            "when the call resolved to one definition.",
            "- Call site: 1-based line of the calling expression.",
            "- Resolution `confirmed_direct`: exactly one definition "
            "within scope addressed the call.",
            "- Resolution `unresolved`: ambiguous (competing "
            "definitions), out of the analyzed set, or reached through "
            "machinery the conservative parser does not interpret "
            "(function pointers, macro-generated code). Unresolved "
            "edges are expected limits, not errors; grouping them by "
            "callee shows which names need external evidence.",
            "",
        ]
        if not data.edges:
            lines.extend(
                (
                    "## Calls by caller",
                    "",
                    "_No resolved direct calls. Run `cintel analyze` "
                    "first. (unavailable information)_",
                    "",
                )
            )
        else:
            by_caller: dict[tuple[str, str], list[CallGraphEdge]] = {}
            for edge in resolved:
                by_caller.setdefault(
                    (edge.caller_path, edge.caller), []
                ).append(edge)
            lines.extend(("## Calls by caller", ""))
            if not resolved:
                lines.append("_No calls resolved to a definition in the "
                             "analyzed scope. (unavailable information)_")
                lines.append("")
            for caller_path, caller in sorted(by_caller):
                edges = sorted(
                    by_caller[(caller_path, caller)],
                    key=lambda item: (item.call_site_line, item.callee),
                )
                heading = caller or "(unresolved caller)"
                lines.extend((f"### {heading} (`{_escape(caller_path)}`)", ""))
                lines.append("Callees:")
                for edge in edges:
                    callee = f"`{edge.callee}`"
                    if edge.callee_path is not None:
                        callee += (
                            f" (`{_escape(edge.callee_path)}:"
                            f"{edge.callee_line}`)"
                        )
                    lines.append(
                        f"- {callee} — call site {edge.call_site_line}"
                    )
                lines.append("")
            lines.append("## Unresolved calls")
            lines.append("")
            if not unresolved:
                lines.append("No unresolved direct calls.")
                lines.append("")
            else:
                by_callee: dict[str, list[CallGraphEdge]] = {}
                for edge in unresolved:
                    by_callee.setdefault(edge.callee, []).append(edge)
                for callee in sorted(by_callee):
                    references = sorted(
                        by_callee[callee],
                        key=lambda item: (
                            item.caller_path,
                            item.caller,
                            item.call_site_line,
                        ),
                    )
                    heading = callee or "(unknown callee spelling)"
                    lines.extend(
                        (
                            f"### `{heading}` "
                            f"({len(references)} call sites)",
                            "",
                        )
                    )
                    lines.append("Called from:")
                    for edge in references:
                        caller = edge.caller or "(unresolved caller)"
                        caller_text = (
                            f"`{_escape(caller)}` "
                            f"(`{_escape(edge.caller_path)}`"
                            f":{edge.call_site_line})"
                        )
                        lines.append(f"- {caller_text}")
                    lines.append("")
        return "\n".join(lines)

    def _include_index(self, data: IncludeIndexReportData) -> str:
        _require(data, IncludeIndexReportData, "include_index")
        unresolved_entries = tuple(
            entry for entry in data.entries
            if entry.resolved_path is None
        )
        resolved_entries = tuple(
            entry for entry in data.entries
            if entry.resolved_path is not None
        )
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
            "compilation unit's `-I` paths. Unresolved directives are "
            "listed first, grouped by spelling, so the headers the "
            "analysis cannot see are immediately visible; resolved "
            "directives follow, grouped by including file.",
            "",
            "## Value meanings",
            "",
            "- Included: the spelling exactly as written after "
            "`#include` (angle brackets and quotes included).",
            "- Referenced from: the files holding the directive, with "
            "1-based lines.",
            "- Unresolved: no matching file in the search paths — "
            "typical for system headers (`<stdio.h>`) and generated "
            "headers that do not exist yet. This is an explicitly "
            "reported limit, not an error.",
            "- Resolved: the found file's repository-relative path.",
            "",
        ]
        if not data.entries:
            lines.append("_No analyzed includes. Run `cintel analyze` first. "
                         "(unavailable information)_")
        else:
            lines.extend(("## Unresolved includes", ""))
            if not unresolved_entries:
                lines.append("No unresolved include directives.")
                lines.append("")
            else:
                by_spelling: dict[str, list[IncludeIndexEntry]] = {}
                for entry in unresolved_entries:
                    by_spelling.setdefault(entry.included_spelling, []).append(
                        entry
                    )
                for spelling in sorted(by_spelling):
                    references = sorted(
                        by_spelling[spelling],
                        key=lambda item: (
                            item.including_path,
                            item.line,
                        ),
                    )
                    lines.extend(
                        (
                            f"### `{_escape(spelling)}` "
                            f"({len(references)} directives)",
                            "",
                        )
                    )
                    lines.append("Referenced from:")
                    for entry in references:
                        lines.append(
                            f"- `{_escape(entry.including_path)}:"
                            f"{entry.line}`"
                        )
                    lines.append("")
            lines.append("## Resolved includes")
            lines.append("")
            if not resolved_entries:
                lines.append("No resolved include directives.")
                lines.append("")
            else:
                by_including: dict[str, list[IncludeIndexEntry]] = {}
                for entry in resolved_entries:
                    by_including.setdefault(entry.including_path, []).append(
                        entry
                    )
                for including_path in sorted(by_including):
                    directives = sorted(
                        by_including[including_path],
                        key=lambda item: (item.line, item.included_spelling),
                    )
                    lines.extend(
                        (f"### `{_escape(including_path)}`", "")
                    )
                    lines.append("Included:")
                    for entry in directives:
                        lines.append(
                            f"- line {entry.line}: "
                            f"`{_escape(entry.included_spelling)}` → "
                            f"`{_escape(entry.resolved_path)}`"
                        )
                    lines.append("")
        return "\n".join(lines)

    def _symbol_index(self, data: SymbolIndexReportData) -> str:
        _require(data, SymbolIndexReportData, "symbol_index")
        by_kind: dict[str, list[SymbolIndexEntry]] = {}
        for entry in data.entries:
            by_kind.setdefault(entry.kind, []).append(entry)
        lines = [
            "# Symbol Index",
            "",
            f"- Symbols recorded: {len(data.entries)} *(calculated metric)*",
            "",
            "## What this report means",
            "",
            "Named things the conservative parser found while analyzing "
            "source files: functions, file-scope variables, named types, "
            "and macros. It is organized one section per kind with "
            "symbols alphabetized by name, so a symbol lookup needs no "
            "scanning; `symbol_index.json` keeps location order for "
            "machine consumption. This is the lookup table behind "
            "`cintel symbols` and the store behind `symbol_index.json` "
            "fixture validation.",
            "",
            "## Value meanings",
            "",
            "- Sections: `function`, `variable` (file-scope objects), "
            "`type` (structs, unions, enums, typedefs, opaque types), "
            "`macro` (`#define`).",
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
            for kind in sorted(by_kind):
                entries = sorted(
                    by_kind[kind],
                    key=lambda item: (item.name, item.relative_path, item.line),
                )
                lines.extend(
                    (
                        f"## {kind.capitalize()}s ({len(entries)})",
                        "",
                        "| Symbol | State | Location |",
                        "|---|---|---|",
                    )
                )
                for entry in entries:
                    state = (
                        "n/a"
                        if entry.is_definition is None
                        else ("definition" if entry.is_definition else "declaration")
                    )
                    lines.append(
                        f"| {entry.name} | {state} | "
                        f"`{_escape(entry.relative_path)}:{entry.line}` |"
                    )
                lines.append("")
        return "\n".join(lines)

    def _global_usage(self, data: GlobalUsageReportData) -> str:
        _require(data, GlobalUsageReportData, "global_usage")
        by_variable: dict[str, list[GlobalUsageIndexEntry]] = {}
        for entry in data.entries:
            by_variable.setdefault(entry.variable, []).append(entry)
        functions_touching = {
            (entry.function, entry.function_path) for entry in data.entries
        }
        lines = [
            "# Global Usage",
            "",
            f"- Recorded usages: {len(data.entries)} *(calculated metric)*",
            f"- Globals referenced: {len(by_variable)} *(calculated metric)*",
            f"- Functions touching globals: {len(functions_touching)} "
            "*(calculated metric)*",
            "",
            "## What this report means",
            "",
            "References to file-scope (global) variables found inside "
            "analyzed function bodies. Read and write access is not "
            "distinguished yet. It is organized one section per variable "
            "so the functions that touch a global can be read at a "
            "glance; a variable absent from the list had no usable "
            "reference inside any analyzed function body.",
            "",
            "## Value meanings",
            "",
            "- Variable: the spelling used inside a function body. "
            "Globals may repeat when several analyzed scopes saw them.",
            "- Seen at: the file where the parser located the global. "
            "This is often a declaration in a header rather than the "
            "defining `static`/file-scope row, because the conservative "
            "parser records what it saw. `not parsed` when no matching "
            "symbol was extracted.",
            "- Reference: the enclosing function and the "
            "repository-relative file containing it.",
            "- Machine counterpart: `global_usage.json` keeps one flat "
            "entry per usage; the grouping here is presentation only.",
            "",
        ]
        if not data.entries:
            lines.append(
                "_No recorded global-variable usages. Run "
                "`cintel analyze` first. (unavailable information)_"
            )
        else:
            lines.append("## Globals")
            lines.append("")
            for variable in sorted(by_variable):
                references = sorted(
                    by_variable[variable],
                    key=lambda item: (item.function_path, item.function),
                )
                lines.extend((f"### `{variable}`", ""))
                seen_at = sorted(
                    {
                        entry.variable_path
                        for entry in references
                        if entry.variable_path is not None
                    }
                )
                if seen_at:
                    lines.append(
                        "- Seen at: " + "; ".join(f"`{_escape(path)}`" for path in seen_at)
                    )
                else:
                    lines.append("- Seen at: not parsed")
                lines.append("")
                lines.append("Referenced by:")
                lines.extend(
                    f"- `{_escape(item.function)}` "
                    f"(`{_escape(item.function_path)}`)"
                    for item in references
                )
                lines.append("")
        return "\n".join(lines)

    def _diagnostics_index(self, data: DiagnosticsReportData) -> str:
        _require(data, DiagnosticsReportData, "diagnostics_index")
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
