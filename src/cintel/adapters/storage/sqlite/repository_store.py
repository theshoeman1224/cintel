"""Repository, file, diagnostic, and capability persistence."""

from __future__ import annotations

import json
from datetime import datetime

from cintel.adapters.storage.sqlite.base import StoreBase
from cintel.adapters.storage.sqlite.diagnostics import (
    read_diagnostics,
    replace_diagnostics,
)
from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    FileKind,
    Repository,
    RepositoryFile,
)


class RepositoryStore(StoreBase):

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
        replace_diagnostics(connection, repository_id, diagnostics, context)
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

    def list_capabilities(
        self, repository_id: str
    ) -> tuple[AnalysisCapability, ...]:
        rows = self._connect().execute(
            """
            SELECT name, status, reason, evidence FROM capabilities
            WHERE repository_id = ?
            ORDER BY name
            """,
            (repository_id,),
        ).fetchall()
        return tuple(
            AnalysisCapability(
                name=row[0],
                status=CapabilityStatus(row[1]),
                reason=row[2],
                evidence=tuple(json.loads(row[3])),
            )
            for row in rows
        )

    def list_diagnostics(
        self, repository_id: str, context_prefix: str | None = None
    ) -> tuple[Diagnostic, ...]:
        return read_diagnostics(
            self._connect(), repository_id, context_prefix=context_prefix
        )
