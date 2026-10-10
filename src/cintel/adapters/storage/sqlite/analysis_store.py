"""Source-analysis runs, symbols, and relationship queries."""

from __future__ import annotations

import json
from dataclasses import asdict

from cintel.adapters.storage.serialization import (
    json_default,
    source_analysis_from_parts,
    source_relationship_from_dict,
    source_symbol_from_dict,
)
from cintel.adapters.storage.sqlite.base import StoreBase
from cintel.adapters.storage.sqlite.diagnostics import (
    load_diagnostics,
    replace_diagnostics,
)
from cintel.domain.models import (
    CallEdge,
    CallRelationship,
    FunctionSymbol,
    GlobalUsageEdge,
    GlobalUsageRelationship,
    IncludeEdge,
    IncludeRelationship,
    MacroSymbol,
    SourceAnalysisResult,
    SourceSymbol,
    SymbolOccurrence,
    TypeSymbol,
    VariableSymbol,
)


class AnalysisStore(StoreBase):

    """Source-analysis runs, symbols, and relationship queries."""
    def replace_source_analysis(self, result: SourceAnalysisResult) -> None:
        """Replace one run with its symbols, relationships, and diagnostics."""
        connection = self._connect()
        payload = json.dumps(
            {
                "id": result.id,
                "repository_id": result.repository_id,
                "repository_file_id": result.repository_file_id,
                "compilation_unit_id": result.compilation_unit_id,
                "source_hash": result.source_hash,
                "analysis_fingerprint": result.analysis_fingerprint,
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "status": result.status.value,
                "analyzed_at": result.analyzed_at.isoformat(),
            },
            sort_keys=True,
        )
        connection.execute(
            """
            INSERT INTO source_analysis_runs
              (id, repository_id, repository_file_id, compilation_unit_id,
               source_hash, analysis_fingerprint, parser_name, parser_version,
               status, analyzed_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              source_hash=excluded.source_hash,
              analysis_fingerprint=excluded.analysis_fingerprint,
              parser_name=excluded.parser_name,
              parser_version=excluded.parser_version,
              status=excluded.status,
              analyzed_at=excluded.analyzed_at,
              payload=excluded.payload
            """,
            (
                result.id,
                result.repository_id,
                result.repository_file_id,
                result.compilation_unit_id,
                result.source_hash,
                result.analysis_fingerprint,
                result.parser_name,
                result.parser_version,
                result.status.value,
                result.analyzed_at.isoformat(),
                payload,
            ),
        )
        connection.execute(
            "DELETE FROM source_symbols WHERE analysis_id = ?", (result.id,)
        )
        connection.execute(
            "DELETE FROM source_relationships WHERE analysis_id = ?", (result.id,)
        )
        connection.executemany(
            """
            INSERT INTO source_symbols
              (analysis_id, id, kind, name, repository_id, repository_file_id,
               is_definition, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    result.id,
                    symbol.id,
                    _source_symbol_kind(symbol),
                    symbol.name,
                    result.repository_id,
                    result.repository_file_id,
                    _symbol_is_definition(symbol),
                    json.dumps(asdict(symbol), default=json_default, sort_keys=True),
                )
                for symbol in result.symbols
            ),
        )
        connection.executemany(
            """
            INSERT INTO source_relationships
              (analysis_id, id, kind, repository_id, repository_file_id,
               caller_id, callee_id, callee_spelling, function_id, variable_id,
               variable_spelling, source_file_id, resolved_file_id, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    result.id,
                    relationship.id,
                    _source_relationship_kind(relationship),
                    result.repository_id,
                    result.repository_file_id,
                    *_relationship_projection_values(relationship),
                    json.dumps(
                        asdict(relationship), default=json_default, sort_keys=True
                    ),
                )
                for relationship in result.relationships
            ),
        )
        replace_diagnostics(
            connection,
            result.repository_id,
            result.diagnostics,
            _source_analysis_context(
                result.repository_file_id, result.compilation_unit_id
            ),
        )
        connection.commit()

    def list_source_analyses(
        self, repository_id: str
    ) -> tuple[SourceAnalysisResult, ...]:
        """All stored runs for a repository."""
        rows = self._connect().execute(
            "SELECT id, payload FROM source_analysis_runs WHERE repository_id = ?",
            (repository_id,),
        ).fetchall()
        return tuple(self._load_source_analysis(row[0], row[1]) for row in rows)

    def list_source_analyses_for_file(
        self, repository_file_id: str
    ) -> tuple[SourceAnalysisResult, ...]:
        """Runs for one file; unit-scoped runs first, then a deterministic order."""
        rows = self._connect().execute(
            """
            SELECT id, payload FROM source_analysis_runs
            WHERE repository_file_id = ?
            ORDER BY compilation_unit_id IS NOT NULL, compilation_unit_id, id
            """,
            (repository_file_id,),
        ).fetchall()
        return tuple(self._load_source_analysis(row[0], row[1]) for row in rows)

    def get_source_analysis_for_compilation_unit(
        self, compilation_unit_id: str
    ) -> SourceAnalysisResult | None:
        """Run stored for a unit, or None when absent."""
        row = self._connect().execute(
            """
            SELECT id, payload FROM source_analysis_runs
            WHERE compilation_unit_id = ?
            """,
            (compilation_unit_id,),
        ).fetchone()
        return self._load_source_analysis(row[0], row[1]) if row else None

    def find_symbols(
        self,
        repository_id: str,
        *,
        kind: str | None = None,
        name: str | None = None,
    ) -> tuple[SymbolOccurrence, ...]:
        """Symbol occurrences with optional kind and exact-name filters."""
        query = """
            SELECT s.analysis_id, s.kind, s.payload, r.repository_file_id,
                   r.compilation_unit_id
            FROM source_symbols AS s
            JOIN source_analysis_runs AS r ON r.id = s.analysis_id
            WHERE s.repository_id = ?
        """
        arguments: list[str] = [repository_id]
        if kind is not None:
            query += " AND s.kind = ?"
            arguments.append(kind)
        if name is not None:
            query += " AND s.name = ?"
            arguments.append(name)
        query += " ORDER BY s.kind, s.name, s.id, s.analysis_id"
        rows = self._connect().execute(query, tuple(arguments)).fetchall()
        return tuple(
            SymbolOccurrence(
                symbol=source_symbol_from_dict(row_kind, json.loads(row_payload)),
                repository_id=repository_id,
                repository_file_id=row_repository_file_id,
                analysis_id=row_analysis_id,
                compilation_unit_id=row_compilation_unit_id,
            )
            for row_analysis_id, row_kind, row_payload, row_repository_file_id, row_compilation_unit_id in rows
        )

    def get_symbols_by_ids(
        self, repository_id: str, symbol_ids: tuple[str, ...]
    ) -> tuple[SymbolOccurrence, ...]:
        """Occurrences for the given symbol ids; empty input returns ()."""
        if not symbol_ids:
            return ()
        query = f"""
            SELECT s.analysis_id, s.kind, s.payload, r.repository_file_id,
                   r.compilation_unit_id
            FROM source_symbols AS s
            JOIN source_analysis_runs AS r ON r.id = s.analysis_id
            WHERE s.repository_id = ? AND s.id IN ({_placeholders(len(symbol_ids))})
            ORDER BY s.kind, s.name, s.id, s.analysis_id
        """
        rows = self._connect().execute(
            query, (repository_id, *symbol_ids)
        ).fetchall()
        return tuple(
            SymbolOccurrence(
                symbol=source_symbol_from_dict(row_kind, json.loads(row_payload)),
                repository_id=repository_id,
                repository_file_id=row_repository_file_id,
                analysis_id=row_analysis_id,
                compilation_unit_id=row_compilation_unit_id,
            )
            for row_analysis_id, row_kind, row_payload, row_repository_file_id, row_compilation_unit_id in rows
        )

    def find_call_edges(
        self,
        repository_id: str,
        *,
        caller_ids: tuple[str, ...] | None = None,
        callee_ids: tuple[str, ...] | None = None,
        callee_spelling: str | None = None,
    ) -> tuple[CallEdge, ...]:
        """Call edges with optional filters; an empty id filter returns ()."""
        if caller_ids is not None and not caller_ids:
            return ()
        if callee_ids is not None and not callee_ids:
            return ()
        query = """
            SELECT s.analysis_id, s.payload, r.repository_file_id
            FROM source_relationships AS s
            JOIN source_analysis_runs AS r ON r.id = s.analysis_id
            WHERE s.repository_id = ? AND s.kind = 'call'
        """
        arguments: list[str] = [repository_id]
        if caller_ids is not None:
            query += f" AND s.caller_id IN ({_placeholders(len(caller_ids))})"
            arguments.extend(caller_ids)
        if callee_ids is not None:
            query += f" AND s.callee_id IN ({_placeholders(len(callee_ids))})"
            arguments.extend(callee_ids)
        if callee_spelling is not None:
            query += " AND s.callee_spelling = ?"
            arguments.append(callee_spelling)
        query += " ORDER BY s.id, s.analysis_id"
        rows = self._connect().execute(query, tuple(arguments)).fetchall()
        return tuple(
            CallEdge(
                call=source_relationship_from_dict("call", json.loads(row_payload)),
                repository_id=repository_id,
                repository_file_id=row_repository_file_id,
                analysis_id=row_analysis_id,
            )
            for row_analysis_id, row_payload, row_repository_file_id in rows
        )

    def find_global_usage_edges(
        self, repository_id: str
    ) -> tuple[GlobalUsageEdge, ...]:
        """All global-usage edges for a repository."""
        query = """
            SELECT s.analysis_id, s.payload, r.repository_file_id
            FROM source_relationships AS s
            JOIN source_analysis_runs AS r ON r.id = s.analysis_id
            WHERE s.repository_id = ? AND s.kind = 'global_usage'
            ORDER BY s.id, s.analysis_id
        """
        rows = self._connect().execute(query, (repository_id,)).fetchall()
        return tuple(
            GlobalUsageEdge(
                relationship=source_relationship_from_dict(
                    "global_usage", json.loads(row_payload)
                ),
                repository_id=repository_id,
                repository_file_id=row_repository_file_id,
                analysis_id=row_analysis_id,
            )
            for row_analysis_id, row_payload, row_repository_file_id in rows
        )

    def find_include_edges(self, repository_id: str) -> tuple[IncludeEdge, ...]:
        """All include edges for a repository."""
        query = """
            SELECT s.analysis_id, s.payload, r.repository_file_id
            FROM source_relationships AS s
            JOIN source_analysis_runs AS r ON r.id = s.analysis_id
            WHERE s.repository_id = ? AND s.kind = 'include'
            ORDER BY s.id, s.analysis_id
        """
        rows = self._connect().execute(query, (repository_id,)).fetchall()
        return tuple(
            IncludeEdge(
                relationship=source_relationship_from_dict(
                    "include", json.loads(row_payload)
                ),
                repository_id=repository_id,
                repository_file_id=row_repository_file_id,
                analysis_id=row_analysis_id,
            )
            for row_analysis_id, row_payload, row_repository_file_id in rows
        )

    def _load_source_analysis(
        self, analysis_id: str, payload: str
    ) -> SourceAnalysisResult:
        connection = self._connect()
        symbol_rows = connection.execute(
            """
            SELECT kind, payload FROM source_symbols
            WHERE analysis_id = ? ORDER BY kind, name, id
            """,
            (analysis_id,),
        ).fetchall()
        relationship_rows = connection.execute(
            """
            SELECT kind, payload FROM source_relationships
            WHERE analysis_id = ? ORDER BY kind, id
            """,
            (analysis_id,),
        ).fetchall()
        data = json.loads(payload)
        diagnostics = load_diagnostics(
            connection,
            data["repository_id"],
            _source_analysis_context(
                data["repository_file_id"], data.get("compilation_unit_id")
            ),
        )
        return source_analysis_from_parts(
            data,
            tuple(
                source_symbol_from_dict(kind, json.loads(item_payload))
                for kind, item_payload in symbol_rows
            ),
            tuple(
                source_relationship_from_dict(kind, json.loads(item_payload))
                for kind, item_payload in relationship_rows
            ),
            diagnostics,
        )


def _source_symbol_kind(symbol: SourceSymbol) -> str:
    if isinstance(symbol, FunctionSymbol):
        return "function"
    if isinstance(symbol, VariableSymbol):
        return "variable"
    if isinstance(symbol, TypeSymbol):
        return "type"
    if isinstance(symbol, MacroSymbol):
        return "macro"
    raise TypeError(f"Unsupported source symbol: {type(symbol).__name__}")


def _symbol_is_definition(symbol: SourceSymbol) -> int | None:
    if isinstance(symbol, (FunctionSymbol, VariableSymbol, TypeSymbol)):
        return int(symbol.is_definition)
    return None


def _relationship_projection_values(
    relationship: IncludeRelationship | CallRelationship | GlobalUsageRelationship,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
    # Projection columns exist so queries filter in SQL; the JSON payload
    # remains the source of truth for reconstruction.
    if isinstance(relationship, CallRelationship):
        return (
            relationship.caller_id,
            relationship.callee_id,
            relationship.callee_spelling,
            None,
            None,
            None,
            None,
            None,
        )
    if isinstance(relationship, GlobalUsageRelationship):
        return (
            None,
            None,
            None,
            relationship.function_id,
            relationship.variable_id,
            relationship.variable_spelling,
            None,
            None,
        )
    if isinstance(relationship, IncludeRelationship):
        return (
            None,
            None,
            None,
            None,
            None,
            None,
            relationship.source_file_id,
            relationship.resolved_file_id,
        )
    raise TypeError(
        f"Unsupported source relationship: {type(relationship).__name__}"
    )


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _source_relationship_kind(
    relationship: IncludeRelationship | CallRelationship | GlobalUsageRelationship,
) -> str:
    if isinstance(relationship, IncludeRelationship):
        return "include"
    if isinstance(relationship, CallRelationship):
        return "call"
    if isinstance(relationship, GlobalUsageRelationship):
        return "global_usage"
    raise TypeError(
        f"Unsupported source relationship: {type(relationship).__name__}"
    )


def _source_analysis_context(
    repository_file_id: str, compilation_unit_id: str | None
) -> str:
    return (
        f"parse:unit:{compilation_unit_id}"
        if compilation_unit_id is not None
        else f"parse:file:{repository_file_id}"
    )
