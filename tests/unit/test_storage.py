import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.storage import SCHEMA_VERSION, SQLiteAnalysisStorage
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    FileKind,
    Repository,
    RepositoryFile,
)


class SQLiteStorageTests(unittest.TestCase):
    def test_initializes_and_persists_phase_one_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteAnalysisStorage(Path(directory) / "index.sqlite")
            storage.initialize()
            repository = Repository(
                id="repository-1",
                root="/repo",
                name="repo",
                created_at=datetime.now(timezone.utc),
            )
            storage.save_repository(repository)
            storage.save_diagnostics(
                repository.id,
                (
                    Diagnostic(
                        code="CI-COMP-001",
                        severity=DiagnosticSeverity.WARNING,
                        message="Compiler unavailable",
                    ),
                ),
            )
            storage.save_capabilities(
                repository.id,
                (
                    AnalysisCapability(
                        name="gcc",
                        status=CapabilityStatus.UNAVAILABLE,
                        reason="Not found",
                    ),
                ),
            )

            self.assertEqual(SCHEMA_VERSION, storage.schema_version())
            self.assertEqual(repository, storage.get_repository(repository.id))
            repository_file = RepositoryFile(
                id="file-1",
                repository_id=repository.id,
                relative_path="main.c",
                absolute_path="/repo/main.c",
                kind=FileKind.C_SOURCE,
                size=10,
                modified_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
            storage.replace_repository_files(repository.id, (repository_file,))
            self.assertEqual(
                (repository_file,), storage.list_repository_files(repository.id)
            )
            storage.replace_repository_files(repository.id, ())
            self.assertEqual((), storage.list_repository_files(repository.id))
            storage.close()

    def test_migrates_an_existing_v1_database_to_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "index.sqlite"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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
                INSERT INTO schema_metadata (key, value)
                VALUES ('schema_version', '1');
                """
            )
            connection.commit()
            connection.close()

            storage = SQLiteAnalysisStorage(database)
            storage.initialize()

            self.assertEqual(3, storage.schema_version())
            self.assertEqual((), storage.list_repository_files("repository-1"))
            storage.close()
