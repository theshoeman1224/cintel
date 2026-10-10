import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from cintel.adapters.artifacts import FileSystemArtifactWriter
from cintel.adapters.parsing import ConservativeCSourceParser
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.analysis import SourceAnalysisService
from cintel.application.context import (
    ContextService,
    _apply_budget,
    render_context_markdown,
)
from cintel.application.queries import FunctionCandidates, SymbolQueryService
from cintel.application.scanning import ScanWorkflowResult
from cintel.configuration.models import AppConfig
from cintel.domain.models import CapabilityStatus, Repository, RepositoryScan
from cintel.utilities.hashing import stable_id

TRUNCATION_MARKER = "… [truncated]"


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


class ContextServiceTests(unittest.TestCase):
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
                created_at=datetime.now(UTC),
            ),
            files=(),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(UTC),
            hashes_computed=0,
            hashes_reused=0,
        )
        self._file_counter = 0
        self.queries = SymbolQueryService(storage_factory=SQLiteAnalysisStorage)
        self.context = ContextService(
            queries=self.queries,
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        )

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
            modified_at=datetime.now(UTC),
            content_sha256="0" * 64,
        )
        self.scan = RepositoryScan(
            repository=self.scan.repository,
            files=self.scan.files + (record,),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(UTC),
            hashes_computed=0,
            hashes_reused=0,
        )

    _SOURCES = {
        "counter.c": (
            "static int counter_value = 0;\n"
            "\n"
            "/* Increments a shared counter.\n"
            " * Thread safety: not guaranteed.\n"
            " */\n"
            "int bump(int amount) {\n"
            "    counter_value += amount;\n"
            "    return counter_value;\n"
            "}\n"
        ),
        "main.c": (
            "#include \"counter.h\"\n"
            "\n"
            "int run(int amount) {\n"
            "    return bump(amount);\n"
            "}\n"
        ),
        "counter.h": "int bump(int amount);\n",
    }

    def test_context_package_contains_expected_sections(self) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        result = self.context.context_function(self.app_config, "bump")

        self.assertNotIsInstance(result, FunctionCandidates)
        package = result.package
        titles = [title for title, _ in package.sections]
        self.assertIn("Definition", titles)
        self.assertIn("Preceding comment", titles)
        self.assertIn("Callers", titles)
        self.assertIn("Callees", titles)
        self.assertIn("Relevant headers", titles)
        self.assertIn("Notes", titles)
        self.assertLessEqual(package.used_characters, package.character_budget)
        definition = dict(package.sections)["Definition"]
        self.assertIn("int bump(int amount) {", definition)
        comment = dict(package.sections).get("Preceding comment", "")
        self.assertIn("Thread safety", comment)
        self.assertIn("unconfigured", dict(package.sections)["Compiler context"])
        self.assertTrue(Path(result.output_path).is_file())
        self.assertEqual(
            "bump__counter_c.md", Path(result.output_path).name
        )

    def test_budget_truncates_sections_deterministically(self) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        small = self.context.context_function(
            self.app_config, "bump", budget=120
        )
        large = self.context.context_function(
            self.app_config, "bump", budget=8000
        )
        small_titles = [title for title, _ in small.package.sections]
        large_titles = [title for title, _ in large.package.sections]
        self.assertLess(len(small_titles), len(large_titles))
        self.assertEqual("Omitted sections", small.package.sections[-1][0])
        self.assertTrue(
            small.package.sections[-1][1].endswith("… [truncated]")
        )
        self.assertIn(
            "Omitted sections",
            [title for title, _ in self.context.context_function(
                self.app_config, "bump", budget=500
            ).package.sections],
        )
        self.assertLessEqual(
            small.package.used_characters, small.package.character_budget
        )
        self.assertEqual(
            render_context_markdown(small.package),
            render_context_markdown(
                self.context.context_function(
                    self.app_config, "bump", budget=120
                ).package
            ),
        )

    def test_ambiguous_name_returns_candidates_without_writing(self) -> None:
        self._write_source(
            "first.c", "static int shared(int v) { return v; }\n"
        )
        self._write_source(
            "second.c", "static int shared(int v) { return v + 1; }\n"
        )
        self._analyze()

        result = self.context.context_function(self.app_config, "shared")

        self.assertIsInstance(result, FunctionCandidates)
        self.assertFalse((self.output / "context").exists())

    def test_rejects_non_positive_budget(self) -> None:
        with self.assertRaises(ValueError):
            self.context.context_function(
                self.app_config, "anything", budget=0
            )

    def test_budget_exact_fit_keeps_every_section(self) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        large = self.context.context_function(
            self.app_config, "bump", budget=8000
        ).package
        exact = self.context.context_function(
            self.app_config, "bump", budget=large.used_characters
        ).package

        self.assertEqual(large.sections, exact.sections)
        self.assertEqual(large.used_characters, exact.used_characters)
        self.assertEqual(
            CapabilityStatus.AVAILABLE, exact.capabilities[0].status
        )
        self.assertEqual(
            "all sections fit the budget", exact.capabilities[0].reason
        )

    def test_budget_one_below_fit_omits_only_the_tail(self) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        large = self.context.context_function(
            self.app_config, "bump", budget=8000
        ).package
        squeezed = self.context.context_function(
            self.app_config, "bump", budget=large.used_characters - 1
        ).package

        self.assertEqual(large.sections[:-1], squeezed.sections[:-1])
        self.assertEqual("Omitted sections", squeezed.sections[-1][0])
        self.assertEqual("Notes", squeezed.sections[-1][1])
        self.assertLessEqual(
            squeezed.used_characters, squeezed.character_budget
        )
        self.assertEqual(
            CapabilityStatus.DEGRADED, squeezed.capabilities[0].status
        )

    def test_first_section_truncates_to_the_remaining_budget(self) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        large = self.context.context_function(
            self.app_config, "bump", budget=8000
        ).package
        definition_body = dict(large.sections)["Definition"]
        truncated = self.context.context_function(
            self.app_config,
            "bump",
            budget=len("Definition") + len(TRUNCATION_MARKER) + 5,
        ).package

        self.assertEqual(
            (("Definition", definition_body[:5] + TRUNCATION_MARKER),),
            truncated.sections,
        )
        self.assertEqual(
            truncated.character_budget, truncated.used_characters
        )

    def test_tiny_budget_yields_empty_package_and_degraded_capability(
        self,
    ) -> None:
        for relative_path, content in self._SOURCES.items():
            self._write_source(relative_path, content)
        self._analyze()

        package = self.context.context_function(
            self.app_config, "bump", budget=5
        ).package

        self.assertEqual((), package.sections)
        self.assertEqual(0, package.used_characters)
        self.assertEqual(
            CapabilityStatus.DEGRADED, package.capabilities[0].status
        )
        self.assertIn(
            "exceeded the 5 character budget",
            package.capabilities[0].reason,
        )

    def test_globals_section_lists_each_variable_once_with_location(
        self,
    ) -> None:
        self._write_source(
            "state.c",
            "int shared_state = 0;\n"
            "\n"
            "int read_twice(void) {\n"
            "    shared_state += 1;\n"
            "    return shared_state;\n"
            "}\n",
        )
        self._write_source(
            "main.c",
            "int read_twice(void);\n"
            "\n"
            "int main(void) { return read_twice(); }\n",
        )
        self._analyze()

        package = self.context.context_function(
            self.app_config, "read_twice"
        ).package

        self.assertEqual(
            "shared_state: int (state.c:1)",
            dict(package.sections)["Globals used"],
        )


class ApplyBudgetBoundaryTests(unittest.TestCase):
    """Characterizes _apply_budget arithmetic beyond reachable service data."""

    def _detail(self) -> SimpleNamespace:
        return SimpleNamespace(
            definition=SimpleNamespace(
                symbol_id="function-1",
                name="bump",
                relative_path="counter.c",
                line=1,
            )
        )

    def test_exact_fit_includes_all_sections_without_banner(self) -> None:
        package = _apply_budget(
            [("A", "x" * 10), ("BB", "y" * 10)], 23, self._detail()
        )

        self.assertEqual(
            (("A", "x" * 10), ("BB", "y" * 10)), package.sections
        )
        self.assertEqual(23, package.used_characters)
        self.assertEqual(
            CapabilityStatus.AVAILABLE, package.capabilities[0].status
        )

    def test_first_section_truncation_uses_its_own_remaining_budget(
        self,
    ) -> None:
        package = _apply_budget([("A", "x" * 30)], 20, self._detail())

        self.assertEqual(
            (("A", "x" * 6 + TRUNCATION_MARKER),), package.sections
        )
        self.assertEqual(20, package.used_characters)
        self.assertEqual(
            CapabilityStatus.DEGRADED, package.capabilities[0].status
        )

    def test_omitted_banner_truncates_when_the_body_does_not_fit(self) -> None:
        long_title = "T" * 20
        package = _apply_budget(
            [("A", "x" * 5), (long_title, "y" * 50)], 38, self._detail()
        )

        self.assertEqual(
            (
                ("A", "x" * 5),
                ("Omitted sections", "TTT" + TRUNCATION_MARKER),
            ),
            package.sections,
        )
        self.assertEqual(38, package.used_characters)

    def test_no_room_for_any_output_leaves_no_sections(self) -> None:
        package = _apply_budget([("A", "x" * 30)], 5, self._detail())

        self.assertEqual((), package.sections)
        self.assertEqual(0, package.used_characters)
        self.assertEqual(
            CapabilityStatus.DEGRADED, package.capabilities[0].status
        )


if __name__ == "__main__":
    unittest.main()
