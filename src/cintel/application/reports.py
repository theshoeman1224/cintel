"""Generation of the Phase 6 Markdown/JSON report families.

The service refreshes the scan-owned repository inventory (incrementally)
and renders every other family from persisted state. All writes go through
the artifact writer; per-family failures produce ``CI-GEN-001`` diagnostics
instead of aborting the remaining families.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cintel.application.scanning import RepositoryScanService
from cintel.application.storage_session import storage_session
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.errors import ConfigurationError
from cintel.domain.models import (
    BuildSelectionEntry,
    BuildSelectionReportData,
    CallGraphEdge,
    CallGraphReportData,
    CapabilityIndexReportData,
    CompilationUnitEntry,
    CompilationUnitsReportData,
    DiagnosticsReportData,
    FileKind,
    FunctionIndexEntry,
    FunctionSymbol,
    FunctionIndexReportData,
    GeneratedReportMetadata,
    GlobalUsageIndexEntry,
    GlobalUsageReportData,
    IncludeIndexEntry,
    MacroSymbol,
    TypeSymbol,
    VariableSymbol,
    IncludeIndexReportData,
    RepositoryFile,
    RepositoryReportData,
    RepositoryScan,
    SymbolIndexEntry,
    SymbolIndexReportData,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from cintel.configuration.models import AppConfig
from cintel.ports.artifacts import ArtifactWriter
from cintel.ports.services import ReportRenderer
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.hashing import sha256_text, stable_id
from cintel.utilities.paths import stable_repository_id

_REPORT_FAMILIES = (
    "build_selection",
    "compilation_units",
    "function_index",
    "symbol_index",
    "call_graph",
    "include_index",
    "global_usage",
    "diagnostics_index",
    "capability_index",
)


@dataclass(frozen=True, slots=True)
class GeneratedReport:
    report_name: str
    format: str
    path: str


@dataclass(frozen=True, slots=True)
class ReportRunResult:
    repository_id: str
    reports: tuple[GeneratedReport, ...]
    diagnostics: tuple[Diagnostic, ...]


class ReportService:
    def __init__(
        self,
        scanner: RepositoryScanService,
        markdown_renderer: ReportRenderer,
        json_renderer: ReportRenderer,
        artifact_writer: ArtifactWriter,
        storage_factory: Callable[[Path], AnalysisStorage],
    ) -> None:
        self._scanner = scanner
        self._markdown_renderer = markdown_renderer
        self._json_renderer = json_renderer
        self._artifact_writer = artifact_writer
        self._storage_factory = storage_factory

    def generate_all(self, app_config: AppConfig) -> ReportRunResult:
        scan_result = self._scanner.scan(app_config)
        if scan_result.markdown_report is None or scan_result.json_report is None:
            raise ConfigurationError(
                "cintel report requires a scannable repository root"
            )
        reports = [
            GeneratedReport(
                "repository_inventory", "markdown", scan_result.markdown_report
            ),
            GeneratedReport(
                "repository_inventory", "json", scan_result.json_report
            ),
        ]
        diagnostics: list[Diagnostic] = []
        with storage_session(
            self._storage_factory, app_config.database_path
        ) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            data = _gather(storage, repository_id, scan_result.scan)
            output = Path(app_config.output_directory) / "reports"
            for family in _REPORT_FAMILIES:
                for renderer, report_format, suffix in (
                    (self._markdown_renderer, "markdown", "md"),
                    (self._json_renderer, "json", "json"),
                ):
                    try:
                        content = renderer.render(family, data[family])
                        path = output / f"{family}.{suffix}"
                        self._artifact_writer.write_text(path, content)
                    except (ValueError, TypeError, OSError) as exc:
                        diagnostics.append(_generation_failed(family, exc))
                        continue
                    storage.save_report_metadata(
                        GeneratedReportMetadata(
                            id=stable_id(
                                "report", repository_id, family, report_format
                            ),
                            repository_id=repository_id,
                            report_name=family,
                            format=report_format,
                            file_path=str(path.resolve()),
                            content_sha256=sha256_text(content),
                            generated_at=datetime.now(timezone.utc),
                        )
                    )
                    reports.append(
                        GeneratedReport(
                            family, report_format, str(path.resolve())
                        )
                    )
            failed = len(diagnostics)
            storage.save_workflow_state(
                WorkflowState(
                    repository_id=repository_id,
                    stage=WorkflowStage.REPORT,
                    status=(
                        WorkflowStatus.COMPLETED
                        if failed == 0
                        else WorkflowStatus.REDUCED
                    ),
                    updated_at=datetime.now(timezone.utc),
                    details=(("failed_reports", str(failed)),),
                )
            )
        return ReportRunResult(
            repository_id=repository_id,
            reports=tuple(reports),
            diagnostics=tuple(diagnostics),
        )


def _gather(
    storage: AnalysisStorage, repository_id: str, scan: RepositoryScan
) -> dict[str, object]:
    files = storage.list_repository_files(repository_id)
    files_by_id = {item.id: item for item in files}
    configurations = storage.list_build_configurations(repository_id)
    units = storage.list_compilation_units(repository_id)
    analyzed_file_ids = {
        item.repository_file_id
        for item in storage.list_source_analyses(repository_id)
    }
    return {
        "repository_inventory": RepositoryReportData(
            scan=scan,
            build_configurations=configurations,
            compilation_unit_count=len(units),
            analyzed_file_count=len(analyzed_file_ids),
        ),
        "build_selection": BuildSelectionReportData(
            entries=_build_selection(files, configurations, units, files_by_id)
        ),
        "compilation_units": CompilationUnitsReportData(
            entries=_compilation_units(units, configurations, files_by_id)
        ),
        "function_index": _function_index(storage, repository_id, files_by_id),
        "symbol_index": _symbol_index(storage, repository_id, files_by_id),
        "call_graph": _call_graph(storage, repository_id, files_by_id),
        "include_index": _include_index(storage, repository_id, files_by_id),
        "global_usage": _global_usage(storage, repository_id, files_by_id),
        "diagnostics_index": DiagnosticsReportData(
            entries=storage.list_diagnostics(repository_id)
        ),
        "capability_index": CapabilityIndexReportData(
            entries=storage.list_capabilities(repository_id)
        ),
    }


def _build_selection(
    files: tuple[RepositoryFile, ...],
    configurations,
    units,
    files_by_id: dict[str, RepositoryFile],
) -> tuple[BuildSelectionEntry, ...]:
    source_paths = {
        item.relative_path
        for item in files
        if item.kind is FileKind.C_SOURCE
    }
    configuration_names = {item.id: item.name for item in configurations}
    selected_by_configuration: dict[str, set[str]] = {}
    for unit in units:
        name = configuration_names.get(unit.build_configuration_id)
        if name is None or unit.source_file_id is None:
            continue
        origin = files_by_id.get(unit.source_file_id)
        if origin is not None:
            selected_by_configuration.setdefault(name, set()).add(
                origin.relative_path
            )
    return tuple(
        BuildSelectionEntry(
            configuration=configuration.name,
            selected=tuple(
                sorted(selected_by_configuration.get(configuration.name, ()))
            ),
            excluded=tuple(
                sorted(
                    source_paths
                    - selected_by_configuration.get(configuration.name, set())
                )
            ),
        )
        for configuration in configurations
    )


def _compilation_units(
    units, configurations, files_by_id: dict[str, RepositoryFile]
) -> tuple[CompilationUnitEntry, ...]:
    names = {item.id: item.name for item in configurations}
    entries = []
    for unit in units:
        arguments = unit.compiler_invocation.arguments
        source = files_by_id.get(unit.source_file_id)
        entries.append(
            CompilationUnitEntry(
                unit_id=unit.id,
                configuration=names.get(unit.build_configuration_id, "unknown"),
                source_path=source.relative_path if source is not None else None,
                compiler=unit.compiler_invocation.compiler_executable,
                fingerprint=unit.fingerprint,
                define_count=len(arguments.defines),
                include_path_count=len(arguments.include_paths),
            )
        )
    return tuple(
        sorted(
            entries,
            key=lambda item: (item.configuration, item.source_path or "", item.unit_id),
        )
    )


def _function_index(
    storage: AnalysisStorage,
    repository_id: str,
    files_by_id: dict[str, RepositoryFile],
) -> FunctionIndexReportData:
    occurrences = storage.find_symbols(repository_id, kind="function")
    selected: dict[tuple[str, int, str], FunctionIndexEntry] = {}
    for occurrence in occurrences:
        symbol = occurrence.symbol
        origin = files_by_id.get(occurrence.repository_file_id)
        relative_path = origin.relative_path if origin is not None else ""
        key = (relative_path, symbol.location.line, symbol.name)
        if key in selected:
            continue
        selected[key] = FunctionIndexEntry(
            name=symbol.name,
            relative_path=relative_path,
            line=symbol.location.line,
            is_definition=bool(symbol.is_definition),
            linkage=symbol.linkage.value,
        )
    entries = tuple(
        sorted(
            selected.values(),
            key=lambda item: (item.relative_path, item.line, item.name),
        )
    )
    return FunctionIndexReportData(
        entries=entries,
        definition_count=sum(1 for item in entries if item.is_definition),
        declaration_count=sum(1 for item in entries if not item.is_definition),
    )


def _symbol_index(
    storage: AnalysisStorage,
    repository_id: str,
    files_by_id: dict[str, RepositoryFile],
) -> SymbolIndexReportData:
    occurrences = storage.find_symbols(repository_id)
    selected: dict[tuple[str, int, str, str], SymbolIndexEntry] = {}
    for occurrence in occurrences:
        symbol = occurrence.symbol
        origin = files_by_id.get(occurrence.repository_file_id)
        relative_path = origin.relative_path if origin is not None else ""
        linkage = getattr(symbol, "linkage", None)
        key = (
            relative_path,
            symbol.location.line,
            symbol.name,
            _kind_of(symbol),
        )
        if key in selected:
            continue
        selected[key] = SymbolIndexEntry(
            name=symbol.name,
            kind=_kind_of(symbol),
            relative_path=relative_path,
            line=symbol.location.line,
            is_definition=getattr(symbol, "is_definition", None),
            linkage=linkage.value if linkage is not None else None,
        )
    entries = tuple(
        sorted(
            selected.values(),
            key=lambda item: (item.kind, item.relative_path, item.line, item.name),
        )
    )
    return SymbolIndexReportData(entries=entries)


def _kind_of(symbol) -> str:
    if isinstance(symbol, FunctionSymbol):
        return "function"
    if isinstance(symbol, VariableSymbol):
        return "variable"
    if isinstance(symbol, TypeSymbol):
        return "type"
    if isinstance(symbol, MacroSymbol):
        return "macro"
    raise TypeError(f"Unsupported source symbol: {type(symbol).__name__}")


def _global_usage(
    storage: AnalysisStorage,
    repository_id: str,
    files_by_id: dict[str, RepositoryFile],
) -> GlobalUsageReportData:
    edges = storage.find_global_usage_edges(repository_id)
    function_ids = {
        edge.relationship.function_id
        for edge in edges
        if edge.relationship.function_id is not None
    }
    variable_ids = {
        edge.relationship.variable_id
        for edge in edges
        if edge.relationship.variable_id is not None
    }
    symbols = {
        occurrence.symbol.id: occurrence
        for occurrence in storage.get_symbols_by_ids(
            repository_id, tuple(function_ids | variable_ids)
        )
    }

    def _path_of(occurrence) -> str | None:
        origin = files_by_id.get(occurrence.repository_file_id)
        return origin.relative_path if origin is not None else None

    selected: dict[tuple[str, str, str, str | None], GlobalUsageIndexEntry] = {}
    for edge in edges:
        function = symbols.get(edge.relationship.function_id)
        variable = symbols.get(edge.relationship.variable_id or "")
        origin = files_by_id.get(edge.repository_file_id)
        function_path = (
            origin.relative_path
            if origin is not None
            else (_path_of(function) if function is not None else "")
        )
        entry = GlobalUsageIndexEntry(
            function=(
                function.symbol.name
                if function is not None
                else edge.relationship.function_id
            ),
            function_path=function_path,
            variable=edge.relationship.variable_spelling,
            variable_path=_path_of(variable) if variable is not None else None,
        )
        key = (
            entry.function,
            entry.function_path,
            entry.variable,
            entry.variable_path,
        )
        selected.setdefault(key, entry)
    entries = tuple(
        sorted(
            selected.values(),
            key=lambda item: (item.function_path, item.function, item.variable),
        )
    )
    return GlobalUsageReportData(entries=entries)


def _call_graph(
    storage: AnalysisStorage,
    repository_id: str,
    files_by_id: dict[str, RepositoryFile],
) -> CallGraphReportData:
    edges = storage.find_call_edges(repository_id)
    symbol_ids = {
        edge.call.caller_id for edge in edges if edge.call.caller_id is not None
    } | {
        edge.call.callee_id for edge in edges if edge.call.callee_id is not None
    }
    symbols = {
        occurrence.symbol.id: occurrence
        for occurrence in storage.get_symbols_by_ids(
            repository_id, tuple(symbol_ids)
        )
    }

    def _path_of(occurrence) -> str:
        origin = files_by_id.get(occurrence.repository_file_id)
        return origin.relative_path if origin is not None else ""

    selected: dict[tuple[str, str, int, str, str | None, int | None], CallGraphEdge] = {}
    unresolved = 0
    for edge in edges:
        caller = symbols.get(edge.call.caller_id)
        callee = (
            symbols.get(edge.call.callee_id)
            if edge.call.callee_id is not None
            else None
        )
        # Call relationships always originate from the analysis that
        # extracted them, so the calling file is the edge's own file.
        caller_path = _path_of(caller) if caller is not None else ""
        location = edge.call.evidence[0].location if edge.call.evidence else None
        if location is not None:
            call_site_line = location.line
        elif caller is not None:
            call_site_line = caller.symbol.location.line
        else:
            call_site_line = 0
        entry = CallGraphEdge(
            caller=caller.symbol.name if caller is not None else "",
            caller_path=caller_path,
            call_site_line=call_site_line,
            callee=(
                callee.symbol.name
                if callee is not None
                else edge.call.callee_spelling
            ),
            callee_path=_path_of(callee) if callee is not None else None,
            callee_line=(
                callee.symbol.location.line if callee is not None else None
            ),
            resolution=edge.call.resolution.value,
        )
        if entry.resolution != "confirmed_direct":
            unresolved += 1
        key = (
            entry.caller,
            entry.caller_path,
            entry.call_site_line,
            entry.callee,
            entry.callee_path,
            entry.callee_line,
        )
        selected.setdefault(key, entry)
    deduped = tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.caller_path,
                item.call_site_line,
                item.caller,
                item.callee,
            ),
        )
    )
    return CallGraphReportData(edges=deduped, unresolved_count=unresolved)


def _include_index(
    storage: AnalysisStorage,
    repository_id: str,
    files_by_id: dict[str, RepositoryFile],
) -> IncludeIndexReportData:
    edges = storage.find_include_edges(repository_id)
    selected: dict[tuple[str, int, str], IncludeIndexEntry] = {}
    unresolved = 0
    for edge in edges:
        relationship = edge.relationship
        origin = files_by_id.get(edge.repository_file_id)
        if origin is None:
            continue
        location = (
            relationship.evidence[0].location
            if relationship.evidence and relationship.evidence[0].location
            else None
        )
        line = location.line if location is not None else 0
        key = (origin.relative_path, line, relationship.included_spelling)
        if key in selected:
            continue
        resolved_path = None
        if relationship.resolved_file_id is not None:
            target = files_by_id.get(relationship.resolved_file_id)
            resolved_path = (
                target.relative_path
                if target is not None
                else relationship.resolved_file_id
            )
        else:
            unresolved += 1
        selected[key] = IncludeIndexEntry(
            including_path=origin.relative_path,
            line=line,
            included_spelling=relationship.included_spelling,
            resolved_path=resolved_path,
        )
    entries = tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.including_path,
                item.line,
                item.included_spelling,
            ),
        )
    )
    return IncludeIndexReportData(entries=entries, unresolved_count=unresolved)


def _generation_failed(family: str, exc: Exception) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.REPORT_GENERATION_FAILED,
        severity=DiagnosticSeverity.ERROR,
        message=f"Report '{family}' could not be generated: {exc}",
        technical_details=f"{type(exc).__name__}: {exc}",
        missing_capability="report_generation",
        recoverability=Recoverability.REDUCED_CAPABILITY,
        suggested_actions=(
            "Re-run `cintel report` after resolving the underlying error.",
        ),
        related_paths=(f"reports/{family}.md", f"reports/{family}.json"),
        metadata={"report_name": family},
    )
