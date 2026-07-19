from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.errors import StorageError
from cintel.domain.models import (
    AnalysisCapability,
    FileKind,
    GeneratedReportMetadata,
    Repository,
    RepositoryFile,
)

SCHEMA_VERSION = 2


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
        self, repository_id: str, diagnostics: tuple[Diagnostic, ...]
    ) -> None:
        connection = self._connect()
        connection.execute("DELETE FROM diagnostics WHERE repository_id = ?", (repository_id,))
        connection.executemany(
            """
            INSERT INTO diagnostics
              (repository_id, code, severity, message, payload)
            VALUES (?, ?, ?, ?, ?)
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
