import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.parsing import ConservativeCSourceParser
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.analysis import SourceAnalysisService
from cintel.application.scanning import ScanWorkflowResult
from cintel.configuration.models import AppConfig
from cintel.domain.models import (
    CallRelationship,
    Repository,
    RepositoryScan,
    RelationshipResolution,
    WorkflowStatus,
)
from cintel.utilities.hashing import stable_id


class _FakeScanner:
    def __init__(self, scan_provider, storage_factory) -> None:
        self._scan_provider = scan_provider
        self._storage_factory = storage_factory

    def scan(self, config: AppConfig) -> ScanWorkflowResult:
        current_scan = self._scan_provider()
        storage = self._storage_factory(Path(config.database_path))
        storage.initialize()
        try:
            if storage.get_repository(current_scan.repository.id) is None:
                storage.save_repository(current_scan.repository)
            storage.replace_repository_files(
                current_scan.repository.id, current_scan.files
            )
        finally:
            storage.close()
        return ScanWorkflowResult(
            scan=current_scan, markdown_report=None, json_report=None
        )


class SourceAnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.repository_root = self.root / "repo"
        self.repository_root.mkdir()
        self.output = self.root / "analysis"
        self.app_config = AppConfig(
            repository_root=str(self.repository_root),
            output_directory=str(self.output),
            database_path=str(self.output / "index.sqlite"),
        )
        repository_id = stable_id(
            "repository", str(self.repository_root.resolve())
        )
        self.scan = RepositoryScan(
            repository=Repository(
                id=repository_id,
                root=str(self.repository_root),
                name="repo",
                created_at=datetime.now(timezone.utc),
            ),
            files=(),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(timezone.utc),
            hashes_computed=0,
            hashes_reused=0,
        )
        self._file_counter = 0

    def _service(self) -> SourceAnalysisService:
        return SourceAnalysisService(
            parser=ConservativeCSourceParser(),
            scanner=_FakeScanner(lambda: self.scan, SQLiteAnalysisStorage),
            storage_factory=SQLiteAnalysisStorage,
        )

    def _write_source(self, relative_path: str, content: str):
        path = self.repository_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._file_counter += 1
        file_id = stable_id(
            "repository-file", relative_path, str(self._file_counter)
        )
        from cintel.domain.models import FileKind, RepositoryFile

        record = RepositoryFile(
            id=file_id,
            repository_id=self.scan.repository.id,
            relative_path=relative_path,
            absolute_path=str(path),
            kind=(
                FileKind.C_SOURCE if path.suffix == ".c" else FileKind.C_HEADER
            ),
            size=len(content),
            modified_at=datetime.now(timezone.utc),
            content_sha256="0" * 64,
        )
        self.scan = RepositoryScan(
            repository=self.scan.repository,
            files=self.scan.files + (record,),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(timezone.utc),
            hashes_computed=0,
            hashes_reused=0,
        )
        return record

    def test_resolves_static_unique_and_ambiguous_calls_deterministically(self) -> None:
        self._write_source(
            "static_target.c",
            "static int shared(int v) { return v; }\n"
            "int caller_a(void) { return shared(1); }\n",
        )
        self._write_source(
            "unique.c",
            "int unique_target(void) { return 7; }\n"
            "int caller_b(void) { return unique_target(); }\n",
        )
        self._write_source(
            "ambiguous.c",
            "int ambiguous_target(void) { return 1; }\n"
            "int caller_c(void) { return ambiguous_target(); }\n",
        )
        self._write_source(
            "other_definition.c",
            "int ambiguous_target(void) { return 2; }\n",
        )

        summary = self._service().analyze(self.app_config)

        self.assertIs(WorkflowStatus.COMPLETED, summary.status)
        storage = SQLiteAnalysisStorage(Path(self.app_config.database_path))
        storage.initialize()
        try:
            results = {
                result.repository_file_id: result
                for result in storage.list_source_analyses(self.scan.repository.id)
            }
        finally:
            storage.close()
        resolutions = {}
        for result in results.values():
            for relationship in result.relationships:
                if isinstance(relationship, CallRelationship):
                    resolutions[relationship.callee_spelling] = (
                        relationship.resolution,
                        relationship.callee_id,
                    )

        self.assertEqual(
            RelationshipResolution.CONFIRMED_DIRECT,
            resolutions["shared"][0],
            "same-file static definition must win",
        )
        self.assertEqual(
            RelationshipResolution.CONFIRMED_DIRECT,
            resolutions["unique_target"][0],
            "a single definition anywhere resolves",
        )
        self.assertEqual(
            RelationshipResolution.UNRESOLVED,
            resolutions["ambiguous_target"][0],
            "two competing definitions stay unresolved",
        )
        self.assertIsNone(resolutions["ambiguous_target"][1])

    def test_second_run_reuses_results_until_source_changes(self) -> None:
        record = self._write_source(
            "main.c", "int entry(void) { return entry(); }\n"
        )
        service = self._service()

        first = service.analyze(self.app_config)
        second = service.analyze(self.app_config)

        self.assertEqual(1, first.stored_results)
        self.assertEqual(("entry",), first.recursive_functions)
        self.assertEqual(1, second.reused_results)
        self.assertEqual(0, second.stored_results)

        changed = self._rewrite(record, "int entry(void) { return 0; }\n")
        third = service.analyze(self.app_config)
        self.assertEqual(1, third.stored_results)
        self.assertEqual((), third.recursive_functions)

    def _rewrite(self, record, content: str):
        path = Path(record.absolute_path)
        path.write_text(content, encoding="utf-8")
        from dataclasses import replace
        from cintel.utilities.hashing import sha256_text

        updated = replace(
            record,
            content_sha256=sha256_text(content),
            size=len(content),
            modified_at=datetime.now(timezone.utc),
        )
        self.scan = RepositoryScan(
            repository=self.scan.repository,
            files=tuple(
                updated if item.id == record.id else item
                for item in self.scan.files
            ),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(timezone.utc),
            hashes_computed=0,
            hashes_reused=0,
        )
        return updated


if __name__ == "__main__":
    unittest.main()
