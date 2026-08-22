from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.errors import StorageError
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CallRelationship,
    CompilationUnit,
    FileKind,
    FunctionSymbol,
    GeneratedReportMetadata,
    GlobalUsageRelationship,
    IncludeRelationship,
    InputArtifact,
    MacroSymbol,
    Repository,
    RepositoryFile,
    SourceAnalysisResult,
    SourceSymbol,
    TypeSymbol,
    VariableSymbol,
    WorkflowState,
    WorkflowStatus,
)
from cintel.adapters.storage.serialization import (
    build_configuration_from_dict,
    build_result_from_dict,
    compilation_unit_from_dict,
    diagnostic_from_dict,
    diagnostic_to_dict,
    input_artifact_from_dict,
    json_default,
    redact_text,
    sanitized_json,
    source_analysis_from_parts,
    source_relationship_from_dict,
    source_symbol_from_dict,
)
from cintel.adapters.storage.migrations import SCHEMA_VERSION, migrate


class SQLiteAnalysisStorage:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current > SCHEMA_VERSION:
                raise StorageError(
                    f"Database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            migrate(connection, current)
            connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Unable to initialize {self._database_path}: {exc}") from exc

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def save_repository(self, repository: Repository) -> None:
        self._connect().execute(
            """
            INSERT INTO repositories (id, root, name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET root=excluded.root, name=excluded.name
            """,
            (
                repository.id,
                repository.root,
                repository.name,
                repository.created_at.isoformat(),
            ),
        )
        self._connect().commit()

    def get_repository(self, repository_id: str) -> Repository | None:
        row = self._connect().execute(
            "SELECT id, root, name, created_at FROM repositories WHERE id = ?",
            (repository_id,),
        ).fetchone()
        if row is None:
            return None
        return Repository(
            id=row[0],
            root=row[1],
            name=row[2],
            created_at=datetime.fromisoformat(row[3]),
        )

    def list_repository_files(self, repository_id: str) -> tuple[RepositoryFile, ...]:
        rows = self._connect().execute(
            """
            SELECT id, repository_id, relative_path, absolute_path, kind, size,
                   modified_at, content_sha256
            FROM repository_files
            WHERE repository_id = ?
            ORDER BY relative_path
            """,
            (repository_id,),
        ).fetchall()
        return tuple(
            RepositoryFile(
                id=row[0],
                repository_id=row[1],
                relative_path=row[2],
                absolute_path=row[3],
                kind=FileKind(row[4]),
                size=row[5],
                modified_at=datetime.fromisoformat(row[6]),
                content_sha256=row[7],
            )
            for row in rows
        )

    def replace_repository_files(
        self, repository_id: str, files: tuple[RepositoryFile, ...]
    ) -> None:
        connection = self._connect()
        incoming_ids = {item.id for item in files}
        existing_ids = {
            row[0]
            for row in connection.execute(
                "SELECT id FROM repository_files WHERE repository_id = ?",
                (repository_id,),
            )
        }
        connection.executemany(
            """
            INSERT INTO repository_files
              (id, repository_id, relative_path, absolute_path, kind, size,
               modified_at, content_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              absolute_path=excluded.absolute_path,
              kind=excluded.kind,
              size=excluded.size,
              modified_at=excluded.modified_at,
              content_sha256=excluded.content_sha256
            """,
            (
                (
                    item.id,
                    item.repository_id,
                    item.relative_path,
                    item.absolute_path,
                    item.kind.value,
                    item.size,
                    item.modified_at.isoformat(),
                    item.content_sha256,
                )
                for item in files
            ),
        )
        connection.executemany(
            "DELETE FROM repository_files WHERE id = ?",
            ((file_id,) for file_id in existing_ids - incoming_ids),
        )
        connection.commit()

    def save_diagnostics(
        self,
        repository_id: str,
        diagnostics: tuple[Diagnostic, ...],
        context: str = "general",
    ) -> None:
        connection = self._connect()
        _replace_diagnostics(connection, repository_id, diagnostics, context)
        connection.commit()

    def save_capabilities(
        self, repository_id: str, capabilities: tuple[AnalysisCapability, ...]
    ) -> None:
        connection = self._connect()
        connection.execute("DELETE FROM capabilities WHERE repository_id = ?", (repository_id,))
        connection.executemany(
            """
            INSERT INTO capabilities (repository_id, name, status, reason, evidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    repository_id,
                    item.name,
                    item.status.value,
                    item.reason,
                    json.dumps(item.evidence),
                )
                for item in capabilities
            ),
        )
        connection.commit()

    def schema_version(self) -> int:
        row = self._connect().execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0

    def save_report_metadata(self, report: GeneratedReportMetadata) -> None:
        self._connect().execute(
            """
            INSERT INTO generated_reports
              (id, repository_id, report_name, format, file_path,
               content_sha256, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              file_path=excluded.file_path,
              content_sha256=excluded.content_sha256,
              generated_at=excluded.generated_at
            """,
            (
                report.id,
                report.repository_id,
                report.report_name,
                report.format,
                report.file_path,
                report.content_sha256,
                report.generated_at.isoformat(),
            ),
        )
        self._connect().commit()

    def save_build_discovery(self, result: BuildDiscoveryResult) -> None:
        connection = self._connect()
        configuration_payload = sanitized_json(
            asdict(result.configuration), result.configuration
        )
        result_payload = sanitized_json(asdict(result), result.configuration)
        connection.execute(
            """
            INSERT INTO build_configurations
              (id, repository_id, name, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              payload=excluded.payload
            """,
            (
                result.configuration.id,
                result.configuration.repository_id,
                result.configuration.name,
                configuration_payload,
            ),
        )
        connection.execute(
            """
            INSERT INTO build_discovery_runs
              (input_fingerprint, build_configuration_id, build_fingerprint,
               discovered_at, exit_code, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(input_fingerprint) DO UPDATE SET
              build_configuration_id=excluded.build_configuration_id,
              build_fingerprint=excluded.build_fingerprint,
              discovered_at=excluded.discovered_at,
              exit_code=excluded.exit_code,
              payload=excluded.payload
            """,
            (
                result.input_fingerprint,
                result.configuration.id,
                result.build_fingerprint,
                result.discovered_at.isoformat(),
                result.exit_code,
                result_payload,
            ),
        )
        connection.execute(
            "DELETE FROM compiler_invocations WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.execute(
            "DELETE FROM compilation_units WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.execute(
            "DELETE FROM build_commands WHERE build_configuration_id = ?",
            (result.configuration.id,),
        )
        connection.executemany(
            """
            INSERT INTO compiler_invocations
              (id, build_configuration_id, working_directory, source_path, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    item.id,
                    result.configuration.id,
                    item.working_directory,
                    item.source.absolute if item.source else None,
                    sanitized_json(asdict(item), result.configuration),
                )
                for item in result.compiler_invocations
            ),
        )
        connection.executemany(
            """
            INSERT INTO compilation_units
              (id, repository_id, build_configuration_id, source_file_id,
               fingerprint, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    item.id,
                    item.repository_id,
                    item.build_configuration_id,
                    item.source_file_id,
                    item.fingerprint,
                    sanitized_json(asdict(item), result.configuration),
                )
                for item in result.compilation_units
            ),
        )
        connection.executemany(
            """
            INSERT INTO build_commands
              (build_configuration_id, sequence, working_directory,
               classification, raw_content, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    result.configuration.id,
                    sequence,
                    item.working_directory,
                    item.classification,
                    redact_text(item.raw_content, result.configuration),
                    sanitized_json(asdict(item), result.configuration),
                )
                for sequence, item in enumerate(result.commands)
            ),
        )
        connection.commit()

    def get_cached_build_discovery(
        self, input_fingerprint: str
    ) -> BuildDiscoveryResult | None:
        row = self._connect().execute(
            "SELECT payload FROM build_discovery_runs WHERE input_fingerprint = ?",
            (input_fingerprint,),
        ).fetchone()
        return build_result_from_dict(json.loads(row[0])) if row else None

    def list_build_configurations(
        self, repository_id: str
    ) -> tuple[BuildConfiguration, ...]:
        rows = self._connect().execute(
            """
            SELECT payload FROM build_configurations
            WHERE repository_id = ?
            ORDER BY name, id
            """,
            (repository_id,),
        ).fetchall()
        return tuple(build_configuration_from_dict(json.loads(row[0])) for row in rows)

    def list_compilation_units(
        self, repository_id: str, build_configuration_name: str | None = None
    ) -> tuple[CompilationUnit, ...]:
        arguments: list[str] = [repository_id]
        query = """
            SELECT units.payload
            FROM compilation_units AS units
            JOIN build_configurations AS configurations
              ON configurations.id = units.build_configuration_id
            WHERE units.repository_id = ?
        """
        if build_configuration_name is not None:
            query += " AND configurations.name = ?"
            arguments.append(build_configuration_name)
        query += " ORDER BY configurations.name, units.id"
        rows = self._connect().execute(query, tuple(arguments)).fetchall()
        return tuple(compilation_unit_from_dict(json.loads(row[0])) for row in rows)

    def list_diagnostics(
        self, repository_id: str, context_prefix: str | None = None
    ) -> tuple[Diagnostic, ...]:
        return _read_diagnostics(
            self._connect(), repository_id, context_prefix=context_prefix
        )

    def save_input_artifact(self, artifact: InputArtifact) -> None:
        self._connect().execute(
            """
            INSERT INTO input_artifacts
              (id, repository_id, artifact_type, file_path, content_hash,
               validation_status, staleness_status, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              file_path=excluded.file_path,
              validation_status=excluded.validation_status,
              staleness_status=excluded.staleness_status,
              payload=excluded.payload
            """,
            (
                artifact.id,
                artifact.repository_id,
                artifact.artifact_type.value,
                artifact.file_path,
                artifact.content_hash,
                artifact.validation_status.value,
                artifact.staleness_status.value,
                json.dumps(asdict(artifact), default=json_default, sort_keys=True),
            ),
        )
        self._connect().commit()

    def list_input_artifacts(self, repository_id: str) -> tuple[InputArtifact, ...]:
        rows = self._connect().execute(
            "SELECT payload FROM input_artifacts WHERE repository_id = ? ORDER BY id",
            (repository_id,),
        ).fetchall()
        return tuple(input_artifact_from_dict(json.loads(row[0])) for row in rows)

    def save_workflow_state(self, state: WorkflowState) -> None:
        self._connect().execute(
            """
            INSERT INTO workflow_state (repository_id, stage, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repository_id, stage) DO UPDATE SET
              status=excluded.status,
              updated_at=excluded.updated_at,
              payload=excluded.payload
            """,
            (
                state.repository_id,
                state.stage,
                state.status.value,
                state.updated_at.isoformat(),
                json.dumps(dict(state.details), sort_keys=True),
            ),
        )
        self._connect().commit()

    def list_workflow_states(self, repository_id: str) -> tuple[WorkflowState, ...]:
        rows = self._connect().execute(
            """
            SELECT repository_id, stage, status, updated_at, payload
            FROM workflow_state WHERE repository_id = ? ORDER BY updated_at, stage
            """,
            (repository_id,),
        ).fetchall()
        return tuple(
            WorkflowState(
                repository_id=row[0],
                stage=row[1],
                status=WorkflowStatus(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                details=tuple(sorted(json.loads(row[4]).items())),
            )
            for row in rows
        )

    def replace_source_analysis(self, result: SourceAnalysisResult) -> None:
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
            INSERT INTO source_symbols (analysis_id, id, kind, name, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    result.id,
                    symbol.id,
                    _source_symbol_kind(symbol),
                    symbol.name,
                    json.dumps(asdict(symbol), default=json_default, sort_keys=True),
                )
                for symbol in result.symbols
            ),
        )
        connection.executemany(
            """
            INSERT INTO source_relationships (analysis_id, id, kind, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    result.id,
                    relationship.id,
                    _source_relationship_kind(relationship),
                    json.dumps(
                        asdict(relationship), default=json_default, sort_keys=True
                    ),
                )
                for relationship in result.relationships
            ),
        )
        _replace_diagnostics(
            connection,
            result.repository_id,
            result.diagnostics,
            _source_analysis_context(
                result.repository_file_id, result.compilation_unit_id
            ),
        )
        connection.commit()

    def list_source_analyses_for_file(
        self, repository_file_id: str
    ) -> tuple[SourceAnalysisResult, ...]:
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
        row = self._connect().execute(
            """
            SELECT id, payload FROM source_analysis_runs
            WHERE compilation_unit_id = ?
            """,
            (compilation_unit_id,),
        ).fetchone()
        return self._load_source_analysis(row[0], row[1]) if row else None

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
        diagnostics = _load_diagnostics(
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

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._database_path)
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection


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


def _replace_diagnostics(
    connection: sqlite3.Connection,
    repository_id: str,
    diagnostics: tuple[Diagnostic, ...],
    context: str,
) -> None:
    connection.execute(
        "DELETE FROM diagnostics WHERE repository_id = ? AND context_key = ?",
        (repository_id, context),
    )
    connection.executemany(
        """
        INSERT INTO diagnostics
          (repository_id, code, severity, message, payload, context_key)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                repository_id,
                item.code,
                item.severity.value,
                item.message,
                json.dumps(diagnostic_to_dict(item), sort_keys=True),
                context,
            )
            for item in diagnostics
        ),
    )


def _read_diagnostics(
    connection: sqlite3.Connection,
    repository_id: str,
    *,
    exact_context: str | None = None,
    context_prefix: str | None = None,
) -> tuple[Diagnostic, ...]:
    query = (
        "SELECT code, severity, message, payload FROM diagnostics "
        "WHERE repository_id = ?"
    )
    arguments: list[str] = [repository_id]
    if exact_context is not None:
        query += " AND context_key = ?"
        arguments.append(exact_context)
    elif context_prefix is not None:
        query += " AND context_key LIKE ?"
        arguments.append(f"{context_prefix}%")
    query += " ORDER BY id"
    rows = connection.execute(query, tuple(arguments)).fetchall()
    results = []
    for code, severity, message, payload in rows:
        data = json.loads(payload)
        data.update({"code": code, "severity": severity, "message": message})
        results.append(diagnostic_from_dict(data))
    return tuple(results)


def _load_diagnostics(
    connection: sqlite3.Connection, repository_id: str, context: str
) -> tuple[Diagnostic, ...]:
    return _read_diagnostics(connection, repository_id, exact_context=context)
