"""Conservative source analysis with incremental reuse and deterministic resolution."""

from __future__ import annotations

from collections.abc import Callable, ItemsView
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from cintel.application.analysis_capabilities import analysis_capabilities
from cintel.application.analysis_scope import BUILD_CONFIGURATION_DETAIL
from cintel.application.scanning import RepositoryScanService
from cintel.application.storage_session import storage_session
from cintel.configuration.models import AppConfig
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.errors import ConfigurationError
from cintel.domain.models import (
    AnalysisRunSummary,
    CallRelationship,
    CompilationUnit,
    FileKind,
    FunctionSymbol,
    IncludeRelationship,
    Linkage,
    RelationshipResolution,
    RepositoryFile,
    RepositoryScan,
    SourceAnalysisResult,
    SourceAnalysisStatus,
    SourceRelationship,
    SourceSymbol,
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
class _RelationshipCounts:
    resolved_calls: int
    unresolved_calls: int
    resolved_includes: int
    unresolved_includes: int

    @classmethod
    def zero(cls) -> _RelationshipCounts:
        return cls(0, 0, 0, 0)

    def __add__(self, other: _RelationshipCounts) -> _RelationshipCounts:
        return _RelationshipCounts(
            self.resolved_calls + other.resolved_calls,
            self.unresolved_calls + other.unresolved_calls,
            self.resolved_includes + other.resolved_includes,
            self.unresolved_includes + other.unresolved_includes,
        )


@dataclass(frozen=True, slots=True)
class _ResolutionOutcome:
    changed_results: dict[tuple[str, str | None], SourceAnalysisResult]
    resolved_calls: int
    unresolved_calls: int
    resolved_includes: int
    unresolved_includes: int


@dataclass(frozen=True, slots=True)
class _AnalysisInputs:
    units: tuple[CompilationUnit, ...]
    files_by_id: dict[str, RepositoryFile]
    include_dirs_by_unit: dict[str, tuple[str, ...]]
    targets: list[_Target]


@dataclass(frozen=True, slots=True)
class _TargetOutcome:
    results: dict[tuple[str, str | None], SourceAnalysisResult]
    reused: int
    stored: int
    failed: int


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
        """Parse selected targets, resolve relationships, and persist the run."""
        scan_result = self._scanner.scan(app_config)
        blocking = [
            item
            for item in scan_result.scan.diagnostics
            if item.severity is DiagnosticSeverity.ERROR
        ]
        if blocking:
            # Fail before opening storage so a bad path never gets a workspace.
            raise ConfigurationError(
                f"Repository root is not scannable: {app_config.repository_root}. "
                f"{blocking[0].message}"
            )
        scan = scan_result.scan
        repository_id = scan.repository.id
        with storage_session(
            self._storage_factory, app_config.database_path
        ) as storage:
            inputs = _analysis_inputs(storage, scan, build_configuration_name)
            target_outcome = _run_targets(
                self._parser, storage, inputs.targets, force
            )
            outcome = _persist_relationships(
                storage, target_outcome.results, inputs
            )
            entry_points, unreachable, recursive_names = _graph_analytics(
                target_outcome.results.values()
            )
            diagnostics = _run_diagnostics(target_outcome.failed)
            status = _record_analysis_state(
                storage, repository_id, diagnostics, build_configuration_name
            )
            capabilities = analysis_capabilities(
                target_count=len(inputs.targets),
                reused=target_outcome.reused,
                stored=target_outcome.stored,
                failed=target_outcome.failed,
                resolved_calls=outcome.resolved_calls,
                unresolved_calls=outcome.unresolved_calls,
                resolved_includes=outcome.resolved_includes,
                unresolved_includes=outcome.unresolved_includes,
                entry_points=entry_points,
                unreachable=unreachable,
                recursive_count=len(recursive_names),
            )

        return AnalysisRunSummary(
            repository_id=repository_id,
            build_configuration_name=build_configuration_name,
            files_selected=len(inputs.targets),
            units_selected=sum(1 for target in inputs.targets if target.unit),
            reused_results=target_outcome.reused,
            stored_results=target_outcome.stored,
            failed_results=target_outcome.failed,
            resolved_calls=outcome.resolved_calls,
            unresolved_calls=outcome.unresolved_calls,
            resolved_includes=outcome.resolved_includes,
            unresolved_includes=outcome.unresolved_includes,
            entry_points=entry_points,
            unreachable_definitions=unreachable,
            recursive_functions=recursive_names,
            status=status,
            capabilities=capabilities,
            diagnostics=diagnostics,
        )


def _analysis_inputs(
    storage: AnalysisStorage,
    scan: RepositoryScan,
    build_configuration_name: str | None,
) -> _AnalysisInputs:
    units = (
        storage.list_compilation_units(scan.repository.id, build_configuration_name)
        if build_configuration_name is not None
        else ()
    )
    return _AnalysisInputs(
        units=units,
        files_by_id={item.id: item for item in scan.files},
        include_dirs_by_unit=_include_directories(units),
        targets=_select_targets(scan.files, units),
    )


def _run_targets(
    parser: SourceParser,
    storage: AnalysisStorage,
    targets: list[_Target],
    force: bool,
) -> _TargetOutcome:
    results: dict[tuple[str, str | None], SourceAnalysisResult] = {}
    reused = stored = failed = 0
    for target in targets:
        expected = parser.analysis_fingerprint(target.file, target.unit)
        existing = None if force else _stored_result(storage, target)
        if existing is not None and existing.analysis_fingerprint == expected:
            results[target.key] = existing
            reused += 1
            continue
        result = parser.parse(target.file, target.unit)
        storage.replace_source_analysis(result)
        results[target.key] = result
        stored += 1
        if result.status is SourceAnalysisStatus.FAILED:
            failed += 1
    return _TargetOutcome(
        results=results, reused=reused, stored=stored, failed=failed
    )


def _persist_relationships(
    storage: AnalysisStorage,
    results: dict[tuple[str, str | None], SourceAnalysisResult],
    inputs: _AnalysisInputs,
) -> _ResolutionOutcome:
    if not results:
        return _ResolutionOutcome(
            changed_results={},
            resolved_calls=0,
            unresolved_calls=0,
            resolved_includes=0,
            unresolved_includes=0,
        )
    outcome = _resolve_relationships(
        results,
        inputs.files_by_id,
        inputs.include_dirs_by_unit,
        frozenset(
            unit.source_file_id
            for unit in inputs.units
            if unit.source_file_id is not None
        ),
    )
    for key in sorted(outcome.changed_results):
        storage.replace_source_analysis(outcome.changed_results[key])
        results[key] = outcome.changed_results[key]
    return outcome


def _record_analysis_state(
    storage: AnalysisStorage,
    repository_id: str,
    diagnostics: tuple[Diagnostic, ...],
    build_configuration_name: str | None,
) -> WorkflowStatus:
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
            updated_at=datetime.now(UTC),
            # Queries and reports rebuild their scope from this name.
            details=(
                (BUILD_CONFIGURATION_DETAIL, build_configuration_name or ""),
            ),
        )
    )
    return status


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
    member_file_ids: frozenset[str] | None = None,
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
    else:
        # A call inside a build-configured compilation unit can only link
        # against definitions that are themselves members of that build;
        # definitions in excluded sources must not resolve the call.
        if origin.compilation_unit_id is not None and member_file_ids:
            candidates = [
                (result, symbol)
                for result, symbol in candidates
                if result.repository_file_id in member_file_ids
            ]
        if len(candidates) == 1:
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
    member_file_ids: frozenset[str] | None = None,
) -> _ResolutionOutcome:
    definitions = _function_definitions(results.items())
    definition_ids = frozenset(
        symbol.id for entries in definitions.values() for _, symbol in entries
    )
    files_by_absolute = {
        str(normalized_path(Path(item.absolute_path))): item
        for item in files_by_id.values()
    }

    changed_results: dict[tuple[str, str | None], SourceAnalysisResult] = {}
    counts = _RelationshipCounts.zero()

    for key, result in sorted(results.items()):
        search_directories = _include_search_directories(
            result, files_by_id, include_dirs_by_unit
        )
        relationships, result_changed = _rebuild_relationships(
            result, definitions, definition_ids, search_directories,
            files_by_absolute, member_file_ids,
        )
        counts += _count_relationships(relationships)
        if result_changed:
            changed_results[key] = replace(
                result,
                relationships=tuple(relationships),
            )

    return _ResolutionOutcome(
        changed_results=changed_results,
        resolved_calls=counts.resolved_calls,
        unresolved_calls=counts.unresolved_calls,
        resolved_includes=counts.resolved_includes,
        unresolved_includes=counts.unresolved_includes,
    )


def _rebuild_relationships(
    result: SourceAnalysisResult,
    definitions,
    definition_ids: frozenset[str],
    search_directories: tuple[str, ...],
    files_by_absolute: dict[str, RepositoryFile],
    member_file_ids: frozenset[str] | None = None,
) -> tuple[list, bool]:
    relationships = []
    result_changed = False
    # Resolution is monotonic: only unresolved calls are retried, so an
    # already-resolved call keeps its target when a later pass introduces a
    # competing definition. --force-analysis rebuilds from scratch instead.
    # The exception is a target outside this run: a file-scoped result shared
    # by several runs may still point at another configuration's definition.
    for relationship in result.relationships:
        new_relationship = relationship
        if isinstance(relationship, CallRelationship) and (
            relationship.resolution is RelationshipResolution.UNRESOLVED
            or relationship.callee_id not in definition_ids
        ):
            new_relationship = _resolve_call(
                _unresolved(relationship), result, definitions, member_file_ids
            )
            if new_relationship == relationship:
                new_relationship = relationship
        elif isinstance(relationship, IncludeRelationship):
            new_relationship = _resolve_include(
                relationship, search_directories, files_by_absolute
            )
        if new_relationship is not relationship:
            result_changed = True
        relationships.append(new_relationship)
    return relationships, result_changed


def _unresolved(relationship: CallRelationship) -> CallRelationship:
    if relationship.resolution is RelationshipResolution.UNRESOLVED:
        return relationship
    return replace(
        relationship,
        callee_id=None,
        resolution=RelationshipResolution.UNRESOLVED,
    )


def _count_relationships(
    relationships: list,
) -> _RelationshipCounts:
    resolved_calls = unresolved_calls = 0
    resolved_includes = unresolved_includes = 0
    for relationship in relationships:
        if isinstance(relationship, CallRelationship):
            if relationship.callee_id is not None:
                resolved_calls += 1
            else:
                unresolved_calls += 1
        elif isinstance(relationship, IncludeRelationship):
            if relationship.resolved_file_id is not None:
                resolved_includes += 1
            else:
                unresolved_includes += 1
    return _RelationshipCounts(
        resolved_calls, unresolved_calls, resolved_includes, unresolved_includes
    )


def _graph_analytics(
    results,
) -> tuple[int, int, tuple[str, ...]]:
    definition_names, adjacency, incoming = _build_call_graph(results)
    entry_ids = [node for node in definition_names if not incoming[node]]
    reachable = _reachable_from(entry_ids, adjacency)
    unreachable = len(set(definition_names) - reachable)
    recursive = {
        definition_names[node]
        for node, targets in adjacency.items()
        if node in targets
    }
    return len(entry_ids), unreachable, tuple(sorted(recursive))


def _build_call_graph(
    results,
) -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
    definition_names: dict[str, str] = {}
    incoming: dict[str, set[str]] = {}
    adjacency: dict[str, set[str]] = {}
    for result in results:
        _register_definitions(result.symbols, definition_names, adjacency, incoming)
    for result in results:
        _register_calls(result.relationships, adjacency, incoming)
    return definition_names, adjacency, incoming


def _register_definitions(
    symbols: tuple[SourceSymbol, ...],
    definition_names: dict[str, str],
    adjacency: dict[str, set[str]],
    incoming: dict[str, set[str]],
) -> None:
    for symbol in symbols:
        if isinstance(symbol, FunctionSymbol) and symbol.is_definition:
            definition_names[symbol.id] = symbol.name
            incoming.setdefault(symbol.id, set())
            adjacency.setdefault(symbol.id, set())


def _register_calls(
    relationships: tuple[SourceRelationship, ...],
    adjacency: dict[str, set[str]],
    incoming: dict[str, set[str]],
) -> None:
    for relationship in relationships:
        if isinstance(relationship, CallRelationship) and isinstance(
            relationship.callee_id, str
        ):
            caller = relationship.caller_id
            callee = relationship.callee_id
            if caller in adjacency and callee in incoming:
                adjacency[caller].add(callee)
                incoming[callee].add(caller)


def _reachable_from(entry_ids: list[str], adjacency: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    pending = list(entry_ids)
    while pending:
        node = pending.pop()
        if node in reachable:
            continue
        reachable.add(node)
        pending.extend(adjacency[node] - reachable)
    return reachable


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

