from __future__ import annotations

import json
import shlex
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.application.analysis import AnalysisRunSummary
from cintel.application.context import ContextResult
from cintel.application.initialization import InitializationResult
from cintel.application.queries import (
    FunctionCandidates,
    FunctionDetail,
    SymbolEntry,
    SymbolsResult,
)
from cintel.application.reports import ReportRunResult
from cintel.application.scanning import ScanWorkflowResult
from cintel.domain.models import DoctorReport, RecoveryResult
from cintel.domain.models import BuildDiscoveryResult, CompilationUnit


def render_initialization(result: InitializationResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Initialized Legacy C Code Intelligence for {result.repository.root}",
        f"Configuration: {result.config.output_directory}/config.toml",
        f"Database: {result.config.database_path}",
    ]
    if result.created_paths:
        lines.append(f"Created {len(result.created_paths)} path(s).")
    if result.existing_paths:
        lines.append(f"Reused {len(result.existing_paths)} existing path(s).")
    lines.append("Next: run `cintel --repository <path> doctor`.")
    return "\n".join(lines)


def render_doctor(report: DoctorReport, as_json: bool = False) -> str:
    if as_json:
        return _json(report)
    lines = [
        "Legacy C Code Intelligence doctor",
        f"Repository: {report.repository_root}",
        f"Python: {report.python_version}",
        f"Output writable: {'yes' if report.output_directory_writable else 'no'}",
        "",
        "Tools:",
    ]
    for tool in report.tools:
        state = "available" if tool.available else "unavailable"
        version = f" — {tool.version}" if tool.version else ""
        lines.append(f"  {tool.name}: {state}{version}")
    lines.extend(("", "Detected inputs:"))
    for name, paths in report.detected_inputs.items():
        lines.append(f"  {name}: {len(paths)}")
        lines.extend(f"    {path}" for path in paths[:10])
        if len(paths) > 10:
            lines.append(f"    … {len(paths) - 10} more")
    lines.extend(("", "Capabilities:"))
    for capability in report.capabilities:
        lines.append(f"  {capability.name}: {capability.status.value} — {capability.reason}")
    if report.diagnostics:
        lines.extend(("", "Diagnostics:"))
        for diagnostic in report.diagnostics:
            lines.append(
                f"  [{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
            )
            lines.extend(f"    Action: {action}" for action in diagnostic.suggested_actions)
    lines.extend(("", "Recommended next actions:"))
    lines.extend(f"  - {action}" for action in report.recommended_actions)
    return "\n".join(lines)


def render_scan(result: ScanWorkflowResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    scan = result.scan
    lines = [
        f"Scanned {scan.repository.root}",
        f"Relevant files: {len(scan.files)}",
        f"SHA-256 hashes: {scan.hashes_computed} computed, {scan.hashes_reused} reused",
    ]
    if result.markdown_report:
        lines.append(f"Markdown report: {result.markdown_report}")
    if result.json_report:
        lines.append(f"JSON report: {result.json_report}")
    for diagnostic in scan.diagnostics:
        lines.append(
            f"[{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
        )
    return "\n".join(lines)


def render_build_discovery(
    result: BuildDiscoveryResult, as_json: bool = False
) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Build configuration: {result.configuration.name}",
        f"Make command: {shlex.join(result.make_arguments)}",
        f"Make exit code: {result.exit_code}",
        f"Compiler invocations: {len(result.compiler_invocations)}",
        f"Compilation units: {len(result.compilation_units)}",
        f"Selected source files: {len(result.selected_source_files)}",
        f"Repository sources outside this build: {len(result.excluded_source_files)}",
        f"Missing source files: {len(result.missing_source_files)}",
        "Compiler versions: "
        + (
            ", ".join(f"{name}: {version}" for name, version in result.compiler_versions)
            if result.compiler_versions
            else "unavailable"
        ),
        f"Build fingerprint: {result.build_fingerprint}",
        f"Source: {'cache' if result.from_cache else 'Make dry-run'}",
    ]
    for diagnostic in result.diagnostics:
        lines.append(
            f"[{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
        )
    return "\n".join(lines)


def render_compilation_units(
    units: tuple[CompilationUnit, ...], as_json: bool = False
) -> str:
    if as_json:
        return _json(units)
    if not units:
        return "No compilation units found."
    lines = []
    for unit in units:
        invocation = unit.compiler_invocation
        source = (
            invocation.source.repository_relative or invocation.source.absolute
            if invocation.source
            else "<unknown>"
        )
        object_path = (
            invocation.object_file.repository_relative
            or invocation.object_file.absolute
            if invocation.object_file
            else "<none>"
        )
        lines.extend(
            (
                f"{source}",
                f"  Unit: {unit.id}",
                f"  Build configuration: {unit.build_configuration_id}",
                f"  Compiler: {invocation.compiler_executable}",
                f"  Object: {object_path}",
                f"  Working directory: {invocation.working_directory}",
                f"  Arguments: {shlex.join(invocation.raw_arguments)}",
            )
        )
    return "\n".join(lines)


def render_analysis(result: AnalysisRunSummary, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Source analysis: {result.status.value}",
        f"Targets: {result.files_selected} ({result.units_selected} build-configured)",
        f"Results: {result.stored_results} parsed, {result.reused_results} reused, "
        f"{result.failed_results} failed",
        f"Calls: {result.resolved_calls} resolved, {result.unresolved_calls} unresolved",
        f"Includes resolved: {result.resolved_includes}",
        f"Entry points: {result.entry_points}; "
        f"unreachable definitions: {result.unreachable_definitions}",
        "Directly recursive: "
        + (", ".join(result.recursive_functions) if result.recursive_functions else "none"),
    ]
    for diagnostic in result.diagnostics:
        lines.append(
            f"[{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
        )
    return "\n".join(lines)


def render_recovery(result: RecoveryResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Recovery status: {result.status.value}",
        f"Validated artifacts: {sum(item.validation_status.value == 'valid' for item in result.artifacts)}",
        f"Tracked artifacts: {len(result.artifacts)}",
        f"Instructions: {len(result.instructions)}",
        f"Required-input report: {result.required_inputs_report}",
    ]
    if result.completed_stages:
        lines.append("Completed stages: " + ", ".join(result.completed_stages))
    for diagnostic in result.diagnostics:
        lines.append(
            f"[{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
        )
    for instruction in result.instructions:
        lines.append(
            f"Next: {instruction.title} ({instruction.risk.value}) in {instruction.working_directory}"
        )
    if result.build_result is not None:
        lines.append(f"Recovered compilation units: {len(result.build_result.compilation_units)}")
    return "\n".join(lines)


def render_symbols(result: SymbolsResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    if not result.entries:
        return "No symbols found."
    lines = [f"Symbols: {len(result.entries)}"]
    lines.extend(_symbol_line(entry) for entry in result.entries)
    return "\n".join(lines)


def render_function_detail(
    result: FunctionDetail | FunctionCandidates, as_json: bool = False
) -> str:
    if as_json:
        return _json(result)
    if isinstance(result, FunctionCandidates):
        return _render_candidates(result)
    lines = [
        f"Function: {result.definition.name}",
        f"Location: {result.definition.relative_path}:{result.definition.line}",
        f"Kind: {'definition' if result.definition.is_definition else 'declaration'}"
        f" ({result.definition.linkage or 'unknown'} linkage)",
        f"Signature: {result.definition.detail}",
    ]
    lines.extend(_relationship_block("Callers", result.callers))
    lines.extend(_relationship_block("Callees", result.callees))
    if result.declarations:
        lines.append("Declarations:")
        lines.extend(f"  {_symbol_line(entry)}" for entry in result.declarations)
    return "\n".join(lines)


def render_call_sites(name: str, sites, as_json: bool = False) -> str:
    if as_json:
        return _json(sites)
    if not sites:
        return f"No call relationships found for {name}."
    lines = [f"Call relationships for {name}: {len(sites)}"]
    for site in sites:
        lines.append(
            f"  {site.function_name} ({site.resolution}) at "
            f"{site.relative_path}:{site.line}"
        )
    return "\n".join(lines)


def _render_candidates(result: FunctionCandidates) -> str:
    lines = [
        f"Ambiguous function name: {result.name} "
        f"({len(result.candidates)} definitions); rerun with --file to choose one."
    ]
    lines.extend(f"  {_symbol_line(entry)}" for entry in result.candidates)
    return "\n".join(lines)


def _relationship_block(title: str, sites) -> list[str]:
    if not sites:
        return [f"{title}: none"]
    lines = [f"{title}: {len(sites)}"]
    for site in sites:
        lines.append(
            f"  {site.function_name} ({site.resolution}) at "
            f"{site.relative_path}:{site.line}"
        )
    return lines


def _symbol_line(entry: SymbolEntry) -> str:
    state = "definition" if entry.is_definition else "declaration"
    if entry.is_definition is None:
        state = "symbol"
    return (
        f"{entry.kind} {entry.name} [{state}] {entry.relative_path}:{entry.line}"
        f" {entry.detail}".rstrip()
    )


def render_context_result(
    result: ContextResult | FunctionCandidates, as_json: bool = False
) -> str:
    if as_json:
        return _json(result)
    if isinstance(result, FunctionCandidates):
        return _render_candidates(result)
    package = result.package
    lines = [
        f"Context package: {result.output_path}",
        f"Budget: {package.used_characters} of {package.character_budget} characters",
        f"Sections: {len(package.sections)}",
    ]
    for title, body in package.sections:
        lines.append(f"  {title} ({len(body)} chars)")
    for capability in package.capabilities:
        lines.append(
            f"[{capability.status.value}] {capability.name}: {capability.reason}"
        )
    return "\n".join(lines)


def render_report_run(result: ReportRunResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Reports generated: {len(result.reports)}",
    ]
    for report in result.reports:
        lines.append(f"  {report.report_name} [{report.format}]: {report.path}")
    for diagnostic in result.diagnostics:
        lines.append(
            f"[{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
        )
    return "\n".join(lines)


def _json(value: Any) -> str:
    material = [asdict(item) for item in value] if isinstance(value, tuple) else asdict(value)
    return json.dumps(material, default=_json_default, indent=2, sort_keys=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")
