from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ItemsView

from cintel.application.scanning import RepositoryScanService
from cintel.application.storage_session import storage_session
from cintel.configuration.models import AppConfig
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    AnalysisCapability,
    AnalysisRunSummary,
    CallRelationship,
    CapabilityStatus,
    CompilationUnit,
    FileKind,
    FunctionSymbol,
    IncludeRelationship,
    Linkage,
    RelationshipResolution,
    RepositoryFile,
    SourceAnalysisResult,
    SourceAnalysisStatus,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from cintel.ports.services import SourceParser
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.paths import normalized_path


@dataclass(frozen=True, slots=True)
class _Target:
    file: RepositoryFile
    unit: CompilationUnit | None

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.file.id, self.unit.id if self.unit else None)


@dataclass(frozen=True, slots=True)
class _ResolutionOutcome:
    changed_results: dict[tuple[str, str | None], SourceAnalysisResult]
    resolved_calls: int
    unresolved_calls: int
    resolved_includes: int


class SourceAnalysisService:
    """Orchestrates parsing, cross-file resolution, and incremental reuse."""

    def __init__(
        self,
        parser: SourceParser,
        scanner: RepositoryScanService,
        storage_factory: Callable[[Path], AnalysisStorage],
    ) -> None:
        self._parser = parser
        self._scanner = scanner
        self._storage_factory = storage_factory

    def analyze(
        self,
        app_config: AppConfig,
        build_configuration_name: str | None = None,
        force: bool = False,
    ) -> AnalysisRunSummary:
        scan = self._scanner.scan(app_config).scan
        repository_id = scan.repository.id
        with storage_session(
            self._storage_factory, app_config.database_path
        ) as storage:
            units = (
                storage.list_compilation_units(repository_id, build_configuration_name)
                if build_configuration_name is not None
                else ()
            )
            files_by_id = {item.id: item for item in scan.files}
            include_dirs_by_unit = _include_directories(units)
            targets = _select_targets(scan.files, units)

            results: dict[tuple[str, str | None], SourceAnalysisResult] = {}
            reused = stored = failed = 0
            for target in targets:
                expected = self._parser.analysis_fingerprint(target.file, target.unit)
                existing = None if force else _stored_result(storage, target)
                if (
                    existing is not None
                    and existing.analysis_fingerprint == expected
                ):
                    results[target.key] = existing
                    reused += 1
                    continue
                result = self._parser.parse(target.file, target.unit)
                storage.replace_source_analysis(result)
                results[target.key] = result
                stored += 1
                if result.status is SourceAnalysisStatus.FAILED:
                    failed += 1

            if results:
                outcome = _resolve_relationships(
                    results, files_by_id, include_dirs_by_unit
                )
                for key in sorted(outcome.changed_results):
                    storage.replace_source_analysis(outcome.changed_results[key])
                    results[key] = outcome.changed_results[key]
            else:
                outcome = _ResolutionOutcome({}, 0, 0, 0)

            entry_points, unreachable, recursive_names = _graph_analytics(
                results.values()
            )

            diagnostics = _run_diagnostics(failed)
            if diagnostics:
                storage.save_diagnostics(repository_id, diagnostics, "analysis")
            status = (
                WorkflowStatus.REDUCED if diagnostics else WorkflowStatus.COMPLETED
            )
            storage.save_workflow_state(
                WorkflowState(
                    repository_id=repository_id,
                    stage=WorkflowStage.SOURCE_ANALYSIS,
                    status=status,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            capabilities = _capabilities(
                target_count=len(targets),
                reused=reused,
                stored=stored,
                failed=failed,
                resolved_calls=outcome.resolved_calls,
                unresolved_calls=outcome.unresolved_calls,
                resolved_includes=outcome.resolved_includes,
                entry_points=entry_points,
                unreachable=unreachable,
                recursive_count=len(recursive_names),
            )

        return AnalysisRunSummary(
            repository_id=repository_id,
            build_configuration_name=build_configuration_name,
            files_selected=len(targets),
            units_selected=sum(1 for target in targets if target.unit),
            reused_results=reused,
            stored_results=stored,
            failed_results=failed,
            resolved_calls=outcome.resolved_calls,
            unresolved_calls=outcome.unresolved_calls,
            resolved_includes=outcome.resolved_includes,
            entry_points=entry_points,
            unreachable_definitions=unreachable,
            recursive_functions=recursive_names,
            status=status,
            capabilities=capabilities,
            diagnostics=diagnostics,
        )


def _select_targets(
    scanned_files: tuple[RepositoryFile, ...],
    units: tuple[CompilationUnit, ...],
) -> list[_Target]:
    files_by_id = {item.id: item for item in scanned_files}
    targets: list[_Target] = []
    covered: set[str] = set()
    for unit in units:
        file = files_by_id.get(unit.source_file_id or "")
        if file is None:
            continue
        targets.append(_Target(file=file, unit=unit))
        covered.add(file.id)
    for file in scanned_files:
        if file.kind not in {FileKind.C_SOURCE, FileKind.C_HEADER}:
            continue
        if file.id in covered:
            continue
        targets.append(_Target(file=file, unit=None))
    return targets


def _stored_result(
    storage: AnalysisStorage, target: _Target
) -> SourceAnalysisResult | None:
    if target.unit is not None:
        return storage.get_source_analysis_for_compilation_unit(target.unit.id)
    for result in storage.list_source_analyses_for_file(target.file.id):
        if result.compilation_unit_id is None:
            return result
    return None


def _include_directories(
    units: tuple[CompilationUnit, ...],
) -> dict[str, tuple[str, ...]]:
    directories: dict[str, tuple[str, ...]] = {}
    for unit in units:
        directories[unit.id] = tuple(
            item.path.absolute
            for item in unit.compiler_invocation.arguments.include_paths
        )
    return directories


def _function_definitions(
    results: ItemsView[tuple[str, str | None], SourceAnalysisResult],
) -> dict[str, list[tuple[SourceAnalysisResult, FunctionSymbol]]]:
    definitions: dict[str, list[tuple[SourceAnalysisResult, FunctionSymbol]]] = {}
    for _, result in results:
        for symbol in result.symbols:
            if isinstance(symbol, FunctionSymbol) and symbol.is_definition:
                definitions.setdefault(symbol.name, []).append((result, symbol))
    return definitions


def _resolve_call(
    relationship: CallRelationship,
    origin: SourceAnalysisResult,
    definitions: dict[str, list[tuple[SourceAnalysisResult, FunctionSymbol]]],
) -> CallRelationship:
    candidates = definitions.get(relationship.callee_spelling, ())
    same_file_static = [
        symbol
        for result, symbol in candidates
        if symbol.linkage is Linkage.INTERNAL
        and result.repository_file_id == origin.repository_file_id
    ]
    callee_id: str | None = None
    if same_file_static:
        callee_id = same_file_static[0].id
    elif len(candidates) == 1:
        callee_id = candidates[0][1].id
    if callee_id is None:
        return relationship
    return CallRelationship(
        id=relationship.id,
        caller_id=relationship.caller_id,
        callee_id=callee_id,
        callee_spelling=relationship.callee_spelling,
        resolution=RelationshipResolution.CONFIRMED_DIRECT,
        evidence=relationship.evidence,
        confidence=relationship.confidence,
    )


def _include_search_directories(
    result: SourceAnalysisResult,
    files_by_id: dict[str, RepositoryFile],
    include_dirs_by_unit: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    including_file = files_by_id.get(result.repository_file_id)
    if including_file is None:
        return ()
    directories = [str(Path(including_file.absolute_path).parent)]
    if result.compilation_unit_id is not None:
        directories.extend(include_dirs_by_unit.get(result.compilation_unit_id, ()))
    return tuple(directories)


def _resolve_include(
    relationship: IncludeRelationship,
    search_directories: tuple[str, ...],
    files_by_absolute: dict[str, RepositoryFile],
) -> IncludeRelationship:
    for directory in search_directories:
        candidate = str(
            normalized_path(Path(relationship.included_spelling), Path(directory))
        )
        match = files_by_absolute.get(candidate)
        if match is not None:
            return IncludeRelationship(
                id=relationship.id,
                source_file_id=relationship.source_file_id,
                included_spelling=relationship.included_spelling,
                resolved_file_id=match.id,
                evidence=relationship.evidence,
                confidence=relationship.confidence,
            )
    return relationship


def _resolve_relationships(
    results: dict[tuple[str, str | None], SourceAnalysisResult],
    files_by_id: dict[str, RepositoryFile],
    include_dirs_by_unit: dict[str, tuple[str, ...]],
) -> _ResolutionOutcome:
    definitions = _function_definitions(results.items())
    files_by_absolute = {
        str(normalized_path(Path(item.absolute_path))): item
        for item in files_by_id.values()
    }

    changed_results: dict[tuple[str, str | None], SourceAnalysisResult] = {}
    resolved_calls = unresolved_calls = resolved_includes = 0

    for key, result in sorted(results.items()):
        search_directories = _include_search_directories(
            result, files_by_id, include_dirs_by_unit
        )
        relationships = []
        result_changed = False
        for relationship in result.relationships:
            new_relationship = relationship
            if (
                isinstance(relationship, CallRelationship)
                and relationship.resolution is RelationshipResolution.UNRESOLVED
            ):
                new_relationship = _resolve_call(relationship, result, definitions)
            elif isinstance(relationship, IncludeRelationship):
                new_relationship = _resolve_include(
                    relationship, search_directories, files_by_absolute
                )
            if new_relationship is not relationship:
                result_changed = True
            relationships.append(new_relationship)

        final_result = (
            replace(result, relationships=tuple(relationships))
            if result_changed
            else result
        )
        for relationship in relationships:
            if isinstance(relationship, CallRelationship):
                if relationship.callee_id is not None:
                    resolved_calls += 1
                else:
                    unresolved_calls += 1
            elif (
                isinstance(relationship, IncludeRelationship)
                and relationship.resolved_file_id is not None
            ):
                resolved_includes += 1
        if result_changed:
            changed_results[key] = final_result

    return _ResolutionOutcome(
        changed_results, resolved_calls, unresolved_calls, resolved_includes
    )


def _graph_analytics(
    results,
) -> tuple[int, int, tuple[str, ...]]:
    definition_names: dict[str, str] = {}
    incoming: dict[str, set[str]] = {}
    adjacency: dict[str, set[str]] = {}
    for result in results:
        for symbol in result.symbols:
            if isinstance(symbol, FunctionSymbol) and symbol.is_definition:
                definition_names[symbol.id] = symbol.name
                incoming.setdefault(symbol.id, set())
                adjacency.setdefault(symbol.id, set())
    for result in results:
        for relationship in result.relationships:
            if isinstance(relationship, CallRelationship) and isinstance(
                relationship.callee_id, str
            ):
                caller = relationship.caller_id
                callee = relationship.callee_id
                if caller in adjacency and callee in incoming:
                    adjacency[caller].add(callee)
                    incoming[callee].add(caller)

    entry_ids = [node for node in definition_names if not incoming[node]]
    reachable: set[str] = set()
    pending = list(entry_ids)
    while pending:
        node = pending.pop()
        if node in reachable:
            continue
        reachable.add(node)
        pending.extend(adjacency[node] - reachable)
    unreachable = len(set(definition_names) - reachable)
    recursive = {
        definition_names[node]
        for node, targets in adjacency.items()
        if node in targets
    }
    return len(entry_ids), unreachable, tuple(sorted(recursive))


def _run_diagnostics(failed: int) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if failed:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.SOURCE_ANALYSIS_INCOMPLETE,
                severity=DiagnosticSeverity.WARNING,
                message=(
                    f"{failed} analyzed targets could not be parsed; "
                    "their findings are unavailable."
                ),
                missing_capability="complete_source_analysis",
                recoverability=Recoverability.REDUCED_CAPABILITY,
                suggested_actions=(
                    "Inspect the per-file parse diagnostics for the failing targets.",
                ),
            ),
        )
    return tuple(diagnostics)


def _capabilities(
    *,
    target_count: int,
    reused: int,
    stored: int,
    failed: int,
    resolved_calls: int,
    unresolved_calls: int,
    resolved_includes: int,
    entry_points: int,
    unreachable: int,
    recursive_count: int,
) -> tuple[AnalysisCapability, ...]:
    analysis_status = (
        CapabilityStatus.UNAVAILABLE
        if target_count == 0
        else CapabilityStatus.DEGRADED
        if failed
        else CapabilityStatus.AVAILABLE
    )
    call_status = (
        CapabilityStatus.UNAVAILABLE
        if resolved_calls == 0 and unresolved_calls == 0
        else CapabilityStatus.AVAILABLE
        if unresolved_calls == 0
        else CapabilityStatus.DEGRADED
    )
    graph_status = (
        CapabilityStatus.AVAILABLE
        if definition_graph_exists(entry_points, unreachable, recursive_count)
        else CapabilityStatus.UNAVAILABLE
    )
    return (
        AnalysisCapability(
            name="source_analysis",
            status=analysis_status,
            reason=(
                "Conservative source analysis completed."
                if analysis_status is CapabilityStatus.AVAILABLE
                else "Some analyzed targets could not be parsed."
            ),
            evidence=(
                f"{target_count} targets selected",
                f"{reused} reused",
                f"{stored} parsed",
            ),
        ),
        AnalysisCapability(
            name="call_resolution",
            status=call_status,
            reason="Direct-call candidates resolve to unique definitions.",
            evidence=(
                f"{resolved_calls} resolved",
                f"{unresolved_calls} unresolved",
                f"{resolved_includes} includes resolved",
            ),
        ),
        AnalysisCapability(
            name="entry_point_reachability",
            status=graph_status,
            reason="Reachability and direct-recursion cycles come from resolved calls.",
            evidence=(
                f"{entry_points} entry points",
                f"{unreachable} unreachable definitions",
                f"{recursive_count} directly recursive functions",
            ),
        ),
    )


def definition_graph_exists(entry_points: int, unreachable: int, recursive: int) -> bool:
    return bool(entry_points or unreachable or recursive)
