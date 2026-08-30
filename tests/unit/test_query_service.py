import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.parsing import ConservativeCSourceParser
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.analysis import SourceAnalysisService
from cintel.application.queries import (
    FunctionCandidates,
    FunctionDetail,
    SymbolQueryService,
)
from cintel.application.scanning import ScanWorkflowResult
from cintel.configuration.models import AppConfig
from cintel.domain.models import Repository, RepositoryScan
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


class SymbolQueryServiceTests(unittest.TestCase):
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
        self.queries = SymbolQueryService(storage_factory=SQLiteAnalysisStorage)

    def _analyze(self) -> None:
        SourceAnalysisService(
            parser=ConservativeCSourceParser(),
            scanner=_FakeScanner(lambda: self.scan, SQLiteAnalysisStorage),
            storage_factory=SQLiteAnalysisStorage,
        ).analyze(self.app_config)

    def _write_source(self, relative_path: str, content: str) -> None:
        path = self.repository_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._file_counter += 1
        from cintel.domain.models import FileKind, RepositoryFile

        record = RepositoryFile(
            id=stable_id(
                "repository-file", relative_path, str(self._file_counter)
            ),
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

    def test_symbols_lists_functions_with_filters_and_deduplication(self) -> None:
        self._write_source(
            "unique.c",
            "int unique_target(void) { return 7; }\n"
            "int caller_b(void) { return unique_target(); }\n",
        )
        self._write_source("shared.h", "int shared(int v);\n")
        self._analyze()

        result = self.queries.symbols(self.app_config, kind="function")

        by_name = {entry.name: entry for entry in result.entries}
        self.assertEqual({"unique_target", "caller_b", "shared"}, set(by_name))
        self.assertTrue(by_name["unique_target"].is_definition)
        self.assertFalse(by_name["shared"].is_definition)
        self.assertEqual("shared.h", by_name["shared"].relative_path)
        self.assertEqual("int ()", by_name["unique_target"].detail)

        only_callers = self.queries.symbols(
            self.app_config, kind="function", name="caller_b"
        )
        self.assertEqual(("caller_b",), tuple(
            entry.name for entry in only_callers.entries
        ))

    def test_function_detail_reports_callers_callees_and_declarations(self) -> None:
        self._write_source(
            "unique.c",
            "int unique_target(void) { return 7; }\n"
            "int caller_b(void) { return unique_target(); }\n",
        )
        self._write_source("unique.h", "int unique_target(void);\n")
        self._analyze()

        detail = self.queries.function(self.app_config, "unique_target")

        self.assertIsInstance(detail, FunctionDetail)
        assert isinstance(detail, FunctionDetail)
        self.assertEqual("unique.c", detail.definition.relative_path)
        self.assertTrue(detail.definition.is_definition)
        self.assertEqual(
            ("unique.h",), tuple(item.relative_path for item in detail.declarations)
        )
        self.assertEqual(("caller_b",), tuple(
            site.function_name for site in detail.callers
        ))
        self.assertEqual("unique.c", detail.callers[0].relative_path)
        self.assertEqual(2, detail.callers[0].line)

        reverse = self.queries.function(self.app_config, "caller_b")
        assert isinstance(reverse, FunctionDetail)
        self.assertEqual((), reverse.callers)
        self.assertEqual(("unique_target",), tuple(
            site.function_name for site in reverse.callees
        ))
        self.assertEqual("unique.c", reverse.callees[0].relative_path)
        self.assertEqual(1, reverse.callees[0].line)
        self.assertEqual("confirmed_direct", reverse.callees[0].resolution)

    def test_ambiguous_names_list_candidates_and_file_filter_resolves(self) -> None:
        self._write_source(
            "first.c",
            "static int shared(int v) { return v; }\n"
            "int caller_a(void) { return shared(1); }\n",
        )
        self._write_source(
            "second.c",
            "static int shared(int v) { return v + 1; }\n"
            "int caller_d(void) { return shared(2); }\n",
        )
        self._analyze()

        detail = self.queries.function(self.app_config, "shared")
        self.assertIsInstance(detail, FunctionCandidates)
        assert isinstance(detail, FunctionCandidates)
        self.assertEqual(
            ("first.c", "second.c"),
            tuple(item.relative_path for item in detail.candidates),
        )

        callers = self.queries.callers(self.app_config, "shared")
        self.assertIsInstance(callers, FunctionCandidates)

        selected = self.queries.function(
            self.app_config, "shared", file="second.c"
        )
        self.assertIsInstance(selected, FunctionDetail)
        assert isinstance(selected, FunctionDetail)
        self.assertEqual(("caller_d",), tuple(
            site.function_name for site in selected.callers
        ))

        same_file_static = self.queries.function(
            self.app_config, "shared", file="first.c"
        )
        assert isinstance(same_file_static, FunctionDetail)
        self.assertEqual(("caller_a",), tuple(
            site.function_name for site in same_file_static.callers
        ))

    def test_unknown_names_return_empty_candidates(self) -> None:
        self._write_source("main.c", "int main(void) { return 0; }\n")
        self._analyze()

        detail = self.queries.function(self.app_config, "missing")
        self.assertIsInstance(detail, FunctionCandidates)
        assert isinstance(detail, FunctionCandidates)
        self.assertEqual((), detail.candidates)

        sites = self.queries.callers(self.app_config, "missing")
        self.assertIsInstance(sites, FunctionCandidates)

        listing = self.queries.symbols(self.app_config, name="missing")
        self.assertEqual((), listing.entries)


if __name__ == "__main__":
    unittest.main()
