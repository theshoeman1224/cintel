import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.storage import SCHEMA_VERSION, SQLiteAnalysisStorage
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import AnalysisCapability, CapabilityStatus, Repository


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
            storage.close()

