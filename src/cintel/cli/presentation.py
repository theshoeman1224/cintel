from __future__ import annotations

import json
import shlex
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.application.initialization import InitializationResult
from cintel.application.scanning import ScanWorkflowResult
from cintel.domain.models import DoctorReport
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


def _json(value: Any) -> str:
    material = [asdict(item) for item in value] if isinstance(value, tuple) else asdict(value)
    return json.dumps(material, default=_json_default, indent=2, sort_keys=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")
