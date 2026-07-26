from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4


def migrate(connection: sqlite3.Connection, current_version: int) -> None:
    migrations = (_to_v1, _to_v2, _to_v3, _to_v4)
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
