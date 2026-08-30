"""Read-only symbol and relationship queries over stored source analyses.

The service projects stored analysis state into developer-facing entries.
Because symbol ids embed the compilation-unit scope, the same definition can
appear once per build configuration; every lookup therefore resolves names to
all stored definition ids first and deduplicates results by source location.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cintel.application.storage_session import storage_session
from cintel.domain.models import (
    CallEdge,
    FunctionSymbol,
    MacroSymbol,
    RepositoryFile,
    SourceSymbol,
    SymbolOccurrence,
    TypeSymbol,
    VariableSymbol,
)
from cintel.configuration.models import AppConfig
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.paths import stable_repository_id


@dataclass(frozen=True, slots=True)
class SymbolEntry:
    """One stored symbol presented with its source location."""

    symbol_id: str
    name: str
    kind: str
    relative_path: str
    line: int
    end_line: int | None
    is_definition: bool | None
    linkage: str | None
    detail: str
    analysis_id: str
    compilation_unit_id: str | None


@dataclass(frozen=True, slots=True)
class SymbolsResult:
    repository_id: str
    entries: tuple[SymbolEntry, ...]


@dataclass(frozen=True, slots=True)
class CallSite:
    """A resolved or unresolved direct-call edge.

    For callers, the location is the call site inside the calling function.
    For callees, the location is the callee's definition when the call
    resolved, otherwise the call site inside the calling function.
    """

    function_name: str
    relative_path: str
    line: int
    resolution: str


@dataclass(frozen=True, slots=True)
class FunctionDetail:
    repository_id: str
    definition: SymbolEntry
    declarations: tuple[SymbolEntry, ...]
    callers: tuple[CallSite, ...]
    callees: tuple[CallSite, ...]


@dataclass(frozen=True, slots=True)
class FunctionCandidates:
    """More than one definition matched the requested function name."""

    name: str
    candidates: tuple[SymbolEntry, ...]


class SymbolQueryService:
    def __init__(
        self, storage_factory: Callable[[Path], AnalysisStorage]
    ) -> None:
        self._storage_factory = storage_factory

    def symbols(
        self,
        app_config: AppConfig,
        *,
        kind: str | None = None,
        name: str | None = None,
    ) -> SymbolsResult:
        with storage_session(self._storage_factory, app_config.database_path) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            files_by_id = _files_by_id(storage, repository_id)
            occurrences = storage.find_symbols(
                repository_id, kind=kind, name=name
            )
            entries = _deduplicate(
                _entry(occurrence, files_by_id) for occurrence in occurrences
            )
            return SymbolsResult(repository_id=repository_id, entries=entries)

    def function(
        self,
        app_config: AppConfig,
        name: str,
        *,
        file: str | None = None,
    ) -> FunctionDetail | FunctionCandidates:
        with storage_session(self._storage_factory, app_config.database_path) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            files_by_id = _files_by_id(storage, repository_id)
            occurrences = storage.find_symbols(
                repository_id, kind="function", name=name
            )
            definitions = [item for item in occurrences if item.symbol.is_definition]
            if file is not None:
                definitions = [
                    item
                    for item in definitions
                    if files_by_id[item.repository_file_id].relative_path == file
                ]
            selected = _select_definition(definitions, files_by_id)
            if selected is None:
                candidates = _deduplicate(
                    _entry(item, files_by_id) for item in definitions
                )
                return FunctionCandidates(name=name, candidates=candidates)
            definition, definition_ids = selected
            declarations = _deduplicate(
                _entry(item, files_by_id)
                for item in occurrences
                if not item.symbol.is_definition
            )
            return FunctionDetail(
                repository_id=repository_id,
                definition=definition,
                declarations=declarations,
                callers=self._callers(
                    storage, repository_id, definition, definition_ids, files_by_id
                ),
                callees=self._callees(
                    storage, repository_id, definition, definition_ids, files_by_id
                ),
            )

    def callers(
        self,
        app_config: AppConfig,
        name: str,
        *,
        file: str | None = None,
    ) -> tuple[CallSite, ...] | FunctionCandidates:
        with storage_session(self._storage_factory, app_config.database_path) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            files_by_id = _files_by_id(storage, repository_id)
            definitions = _definitions(storage, repository_id, name, file, files_by_id)
            selected = _select_definition(definitions, files_by_id)
            if selected is None:
                return FunctionCandidates(
                    name=name,
                    candidates=_deduplicate(
                        _entry(item, files_by_id) for item in definitions
                    ),
                )
            definition, definition_ids = selected
            return self._callers(
                storage, repository_id, definition, definition_ids, files_by_id
            )

    def callees(
        self,
        app_config: AppConfig,
        name: str,
        *,
        file: str | None = None,
    ) -> tuple[CallSite, ...] | FunctionCandidates:
        with storage_session(self._storage_factory, app_config.database_path) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            files_by_id = _files_by_id(storage, repository_id)
            definitions = _definitions(storage, repository_id, name, file, files_by_id)
            selected = _select_definition(definitions, files_by_id)
            if selected is None:
                return FunctionCandidates(
                    name=name,
                    candidates=_deduplicate(
                        _entry(item, files_by_id) for item in definitions
                    ),
                )
            definition, definition_ids = selected
            return self._callees(
                storage, repository_id, definition, definition_ids, files_by_id
            )

    def _callers(
        self,
        storage: AnalysisStorage,
        repository_id: str,
        definition: SymbolEntry,
        definition_ids: tuple[str, ...],
        files_by_id: dict[str, RepositoryFile],
    ) -> tuple[CallSite, ...]:
        edges = list(
            storage.find_call_edges(repository_id, callee_ids=definition_ids)
        )
        edges.extend(
            edge
            for edge in storage.find_call_edges(
                repository_id, callee_spelling=definition.name
            )
            if edge.call.callee_id is None
        )
        caller_ids = tuple({edge.call.caller_id for edge in edges})
        callers = {
            occurrence.symbol.id: occurrence
            for occurrence in storage.get_symbols_by_ids(repository_id, caller_ids)
        }
        sites: list[CallSite] = []
        seen: set[tuple[str, str, int, str, str]] = set()
        for edge in edges:
            caller = callers.get(edge.call.caller_id)
            if caller is None:
                continue
            site = _call_site(caller.symbol, edge, files_by_id)
            key = (
                site.function_name,
                site.relative_path,
                site.line,
                edge.call.callee_spelling,
                edge.call.resolution.value,
            )
            if key in seen:
                continue
            seen.add(key)
            sites.append(site)
        return tuple(sorted(sites, key=lambda item: (item.relative_path, item.line, item.function_name)))

    def _callees(
        self,
        storage: AnalysisStorage,
        repository_id: str,
        definition: SymbolEntry,
        definition_ids: tuple[str, ...],
        files_by_id: dict[str, RepositoryFile],
    ) -> tuple[CallSite, ...]:
        edges = list(
            storage.find_call_edges(repository_id, caller_ids=definition_ids)
        )
        callee_ids = tuple(
            {edge.call.callee_id for edge in edges if edge.call.callee_id}
        )
        callees = {
            occurrence.symbol.id: occurrence
            for occurrence in storage.get_symbols_by_ids(repository_id, callee_ids)
        }
        sites: list[CallSite] = []
        seen: set[tuple[str, str, int, str]] = set()
        for edge in edges:
            callee = (
                callees.get(edge.call.callee_id)
                if edge.call.callee_id is not None
                else None
            )
            if callee is not None and isinstance(callee.symbol, FunctionSymbol):
                site = CallSite(
                    function_name=callee.symbol.name,
                    relative_path=files_by_id[
                        callee.repository_file_id
                    ].relative_path,
                    line=callee.symbol.location.line,
                    resolution=edge.call.resolution.value,
                )
            else:
                origin = files_by_id.get(edge.repository_file_id)
                location = edge.call.evidence[0].location if edge.call.evidence else None
                site = CallSite(
                    function_name=edge.call.callee_spelling,
                    relative_path=origin.relative_path if origin else "",
                    line=location.line if location else 0,
                    resolution=edge.call.resolution.value,
                )
            key = (
                site.function_name,
                site.relative_path,
                site.line,
                edge.call.resolution.value,
            )
            if key in seen:
                continue
            seen.add(key)
            sites.append(site)
        return tuple(sorted(sites, key=lambda item: (item.relative_path, item.line, item.function_name)))


def _definitions(
    storage: AnalysisStorage,
    repository_id: str,
    name: str,
    file: str | None,
    files_by_id: dict[str, RepositoryFile],
) -> list[SymbolOccurrence]:
    occurrences = storage.find_symbols(repository_id, kind="function", name=name)
    definitions = [item for item in occurrences if item.symbol.is_definition]
    if file is not None:
        definitions = [
            item
            for item in definitions
            if files_by_id[item.repository_file_id].relative_path == file
        ]
    return definitions


def _select_definition(
    definitions: list[SymbolOccurrence],
    files_by_id: dict[str, RepositoryFile],
) -> tuple[SymbolEntry, tuple[str, ...]] | None:
    """Collapse per-unit duplicates of the same definition.

    Returns the presented entry plus every stored symbol id belonging to that
    definition across compilation units, or ``None`` when the name is
    ambiguous (or absent).
    """

    grouped: dict[tuple[str, int, str], list[SymbolOccurrence]] = {}
    for item in definitions:
        location = item.symbol.location
        relative_path = files_by_id[item.repository_file_id].relative_path
        grouped.setdefault(
            (relative_path, location.line, item.symbol.name), []
        ).append(item)
    if len(grouped) != 1:
        return None
    occurrences = next(iter(grouped.values()))
    entry = _entry(occurrences[0], files_by_id)
    return entry, tuple(item.symbol.id for item in occurrences)


def _files_by_id(
    storage: AnalysisStorage, repository_id: str
) -> dict[str, object]:
    return {
        item.id: item for item in storage.list_repository_files(repository_id)
    }


def _call_site(
    caller: SourceSymbol,
    edge: CallEdge,
    files_by_id: dict[str, RepositoryFile],
) -> CallSite:
    origin = files_by_id.get(edge.repository_file_id)
    location = edge.call.evidence[0].location if edge.call.evidence else None
    return CallSite(
        function_name=caller.name,
        relative_path=getattr(origin, "relative_path", ""),
        line=location.line if location else caller.location.line,
        resolution=edge.call.resolution.value,
    )


def _entry(
    occurrence: SymbolOccurrence, files_by_id: dict[str, RepositoryFile]
) -> SymbolEntry:
    symbol = occurrence.symbol
    location = symbol.location
    origin = files_by_id.get(occurrence.repository_file_id)
    linkage = getattr(symbol, "linkage", None)
    return SymbolEntry(
        symbol_id=symbol.id,
        name=symbol.name,
        kind=_symbol_kind(symbol),
        relative_path=origin.relative_path if origin else "",
        line=location.line,
        end_line=location.end_line,
        is_definition=getattr(symbol, "is_definition", None),
        linkage=linkage.value if linkage is not None else None,
        detail=_detail(symbol),
        analysis_id=occurrence.analysis_id,
        compilation_unit_id=occurrence.compilation_unit_id,
    )


def _symbol_kind(symbol: SourceSymbol) -> str:
    if isinstance(symbol, FunctionSymbol):
        return "function"
    if isinstance(symbol, VariableSymbol):
        return "variable"
    if isinstance(symbol, TypeSymbol):
        return "type"
    if isinstance(symbol, MacroSymbol):
        return "macro"
    raise TypeError(f"Unsupported source symbol: {type(symbol).__name__}")


def _detail(symbol: SourceSymbol) -> str:
    if isinstance(symbol, FunctionSymbol):
        parameters = ", ".join(symbol.parameters)
        return f"{symbol.return_type or '?'} ({parameters})"
    if isinstance(symbol, VariableSymbol):
        return symbol.type_spelling or ""
    if isinstance(symbol, TypeSymbol):
        if symbol.underlying_type:
            return f"{symbol.type_kind}: {symbol.underlying_type}"
        return symbol.type_kind
    if isinstance(symbol, MacroSymbol):
        if symbol.is_function_like:
            parameters = ", ".join(symbol.parameters)
            return f"{symbol.replacement or ''} ({parameters}) function-like"
        return symbol.replacement or ""
    raise TypeError(f"Unsupported source symbol: {type(symbol).__name__}")


def _entry_sort_key(entry: SymbolEntry) -> tuple[str, int, str, str]:
    return (entry.relative_path, entry.line, entry.name, entry.kind)


def _deduplicate(entries) -> tuple[SymbolEntry, ...]:
    """Collapse per-unit duplicates of the same source-location symbol."""

    selected: dict[tuple[str, int, str, str], SymbolEntry] = {}
    for entry in entries:
        key = (entry.relative_path, entry.line, entry.name, entry.kind)
        selected.setdefault(key, entry)
    return tuple(sorted(selected.values(), key=_entry_sort_key))
