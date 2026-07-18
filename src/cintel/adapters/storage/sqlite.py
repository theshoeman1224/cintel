from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.errors import StorageError
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    Repository,
)

SCHEMA_VERSION = 1


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

