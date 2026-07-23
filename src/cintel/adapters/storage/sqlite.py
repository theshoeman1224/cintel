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
    CompilationUnit,
    FileKind,
    GeneratedReportMetadata,
    Repository,
    RepositoryFile,
)
from cintel.adapters.storage.serialization import (
    build_configuration_from_dict,
    build_result_from_dict,
    compilation_unit_from_dict,
    redact_text,
    sanitized_json,
)

SCHEMA_VERSION = 3


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
            if current < 1:
                self._migrate_to_v1(connection)
                current = 1
            if current < 2:
                self._migrate_to_v2(connection)
                current = 2
            if current < 3:
                self._migrate_to_v3(connection)
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
                    json.dumps(
                        {
                            "technical_details": item.technical_details,
                            "missing_capability": item.missing_capability,
                            "recoverability": item.recoverability.value,
                            "suggested_actions": item.suggested_actions,
                            "related_paths": item.related_paths,
                        },
                        sort_keys=True,
                    ),
                    context,
                )
                for item in diagnostics
            ),
        )
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

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._database_path)
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    @staticmethod
    def _migrate_to_v1(connection: sqlite3.Connection) -> None:
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

    @staticmethod
    def _migrate_to_v2(connection: sqlite3.Connection) -> None:
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

    @staticmethod
    def _migrate_to_v3(connection: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(diagnostics)")
        }
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
                build_configuration_id TEXT NOT NULL
                    REFERENCES build_configurations(id),
                build_fingerprint TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                exit_code INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compiler_invocations (
                id TEXT PRIMARY KEY,
                build_configuration_id TEXT NOT NULL
                    REFERENCES build_configurations(id),
                working_directory TEXT NOT NULL,
                source_path TEXT,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS compilation_units (
                id TEXT PRIMARY KEY,
                repository_id TEXT NOT NULL REFERENCES repositories(id),
                build_configuration_id TEXT NOT NULL
                    REFERENCES build_configurations(id),
                source_file_id TEXT,
                fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS compilation_units_source_idx
                ON compilation_units (repository_id, source_file_id);
            CREATE TABLE IF NOT EXISTS build_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_configuration_id TEXT NOT NULL
                    REFERENCES build_configurations(id),
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
