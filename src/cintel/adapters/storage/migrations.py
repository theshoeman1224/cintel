from __future__ import annotations

import json
import sqlite3
from typing import Iterable

SCHEMA_VERSION = 6


def migrate(connection: sqlite3.Connection, current_version: int) -> None:
    migrations = (_to_v1, _to_v2, _to_v3, _to_v4, _to_v5, _to_v6)
    for target_version, migration in enumerate(migrations, 1):
        if current_version < target_version:
            migration(connection)


def _to_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE repositories (
            id TEXT PRIMARY KEY,
            root TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            code TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE capabilities (
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence TEXT NOT NULL,
            PRIMARY KEY (repository_id, name)
        );
        CREATE TABLE workflow_state (
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (repository_id, stage)
        );
        INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '1');
        """
    )


def _to_v2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS repository_files (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            relative_path TEXT NOT NULL,
            absolute_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            UNIQUE (repository_id, relative_path)
        );
        CREATE INDEX IF NOT EXISTS repository_files_kind_idx
            ON repository_files (repository_id, kind);
        CREATE TABLE IF NOT EXISTS generated_reports (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            report_name TEXT NOT NULL,
            format TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            UNIQUE (repository_id, report_name, format)
        );
        UPDATE schema_metadata SET value = '2' WHERE key = 'schema_version';
        """
    )


def _to_v3(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(diagnostics)")}
    if "context_key" not in columns:
        connection.execute(
            "ALTER TABLE diagnostics ADD COLUMN context_key TEXT NOT NULL DEFAULT 'general'"
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS build_configurations (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            name TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS build_configurations_repository_idx
            ON build_configurations (repository_id, name);
        CREATE TABLE IF NOT EXISTS build_discovery_runs (
            input_fingerprint TEXT PRIMARY KEY,
            build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
            build_fingerprint TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS compiler_invocations (
            id TEXT PRIMARY KEY,
            build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
            working_directory TEXT NOT NULL,
            source_path TEXT,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS compilation_units (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
            source_file_id TEXT,
            fingerprint TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS compilation_units_source_idx
            ON compilation_units (repository_id, source_file_id);
        CREATE TABLE IF NOT EXISTS build_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
            sequence INTEGER NOT NULL,
            working_directory TEXT NOT NULL,
            classification TEXT NOT NULL,
            raw_content TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE (build_configuration_id, sequence)
        );
        UPDATE schema_metadata SET value = '3' WHERE key = 'schema_version';
        """
    )


def _to_v4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS input_artifacts (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            artifact_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            staleness_status TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS input_artifacts_repository_idx
            ON input_artifacts (repository_id, artifact_type);
        CREATE TABLE IF NOT EXISTS workflow_state (
            repository_id TEXT NOT NULL REFERENCES repositories(id),
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (repository_id, stage)
        );
        UPDATE schema_metadata SET value = '4' WHERE key = 'schema_version';
        """
    )


def _to_v5(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_analysis_runs (
            id TEXT PRIMARY KEY,
            repository_id TEXT NOT NULL REFERENCES repositories(id)
                ON DELETE CASCADE,
            repository_file_id TEXT NOT NULL REFERENCES repository_files(id)
                ON DELETE CASCADE,
            compilation_unit_id TEXT REFERENCES compilation_units(id)
                ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            analysis_fingerprint TEXT NOT NULL,
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            status TEXT NOT NULL,
            analyzed_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS source_analysis_file_idx
            ON source_analysis_runs (repository_file_id, compilation_unit_id);
        CREATE UNIQUE INDEX IF NOT EXISTS source_analysis_unit_idx
            ON source_analysis_runs (compilation_unit_id)
            WHERE compilation_unit_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS source_symbols (
            analysis_id TEXT NOT NULL REFERENCES source_analysis_runs(id)
                ON DELETE CASCADE,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (analysis_id, id)
        );
        CREATE INDEX IF NOT EXISTS source_symbols_name_idx
            ON source_symbols (name, kind);
        CREATE TABLE IF NOT EXISTS source_relationships (
            analysis_id TEXT NOT NULL REFERENCES source_analysis_runs(id)
                ON DELETE CASCADE,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (analysis_id, id)
        );
        CREATE INDEX IF NOT EXISTS source_relationships_kind_idx
            ON source_relationships (kind);
        UPDATE schema_metadata SET value = '5' WHERE key = 'schema_version';
        """
    )


# Schema v6 adds query-projection columns over the v5 analysis tables. The
# JSON payloads remain the source of truth; the columns exist so symbol and
# call-graph queries can run in SQL without materializing every analysis.
_SYMBOL_DEFINITION_KINDS = ("function", "variable", "type")

_RELATIONSHIP_PROJECTION_COLUMNS = (
    "caller_id",
    "callee_id",
    "callee_spelling",
    "function_id",
    "variable_id",
    "variable_spelling",
    "source_file_id",
    "resolved_file_id",
)


def _to_v6(connection: sqlite3.Connection) -> None:
    _add_columns(
        connection,
        "source_symbols",
        (
            ("repository_id", "TEXT"),
            ("repository_file_id", "TEXT"),
            ("is_definition", "INTEGER"),
        ),
    )
    _add_columns(
        connection,
        "source_relationships",
        (
            ("repository_id", "TEXT"),
            ("repository_file_id", "TEXT"),
            *((name, "TEXT") for name in _RELATIONSHIP_PROJECTION_COLUMNS),
        ),
    )
    _backfill_symbol_projections(connection)
    _backfill_relationship_projections(connection)
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS source_symbols_repository_name_idx
            ON source_symbols (repository_id, kind, name);
        CREATE INDEX IF NOT EXISTS source_symbols_definition_idx
            ON source_symbols (repository_id, name, is_definition);
        CREATE INDEX IF NOT EXISTS source_relationships_repository_kind_idx
            ON source_relationships (repository_id, kind);
        CREATE INDEX IF NOT EXISTS source_relationships_caller_idx
            ON source_relationships (caller_id);
        CREATE INDEX IF NOT EXISTS source_relationships_callee_idx
            ON source_relationships (callee_id);
        UPDATE schema_metadata SET value = '6' WHERE key = 'schema_version';
        """
    )


def _add_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: Iterable[tuple[str, str]],
) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns:
        if name not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
            )


def _backfill_symbol_projections(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT s.analysis_id, s.id, s.kind, s.payload,
               r.repository_id, r.repository_file_id
        FROM source_symbols AS s
        JOIN source_analysis_runs AS r ON r.id = s.analysis_id
        """
    ).fetchall()
    updates = []
    for analysis_id, symbol_id, kind, payload, repository_id, repository_file_id in rows:
        data = json.loads(payload)
        is_definition = (
            int(bool(data["is_definition"]))
            if kind in _SYMBOL_DEFINITION_KINDS and "is_definition" in data
            else None
        )
        updates.append(
            (repository_id, repository_file_id, is_definition, analysis_id, symbol_id)
        )
    connection.executemany(
        """
        UPDATE source_symbols
        SET repository_id = ?, repository_file_id = ?, is_definition = ?
        WHERE analysis_id = ? AND id = ?
        """,
        updates,
    )


def _backfill_relationship_projections(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT s.analysis_id, s.id, s.payload,
               r.repository_id, r.repository_file_id
        FROM source_relationships AS s
        JOIN source_analysis_runs AS r ON r.id = s.analysis_id
        """
    ).fetchall()
    updates = []
    for analysis_id, relationship_id, payload, repository_id, repository_file_id in rows:
        data = json.loads(payload)
        updates.append(
            (
                repository_id,
                repository_file_id,
                *(data.get(name) for name in _RELATIONSHIP_PROJECTION_COLUMNS),
                analysis_id,
                relationship_id,
            )
        )
    connection.executemany(
        f"""
        UPDATE source_relationships
        SET repository_id = ?, repository_file_id = ?,
            {', '.join(f'{name} = ?' for name in _RELATIONSHIP_PROJECTION_COLUMNS)}
        WHERE analysis_id = ? AND id = ?
        """,
        updates,
    )
