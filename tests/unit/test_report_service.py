import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.artifacts import FileSystemArtifactWriter
from cintel.adapters.parsing import ConservativeCSourceParser
from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.analysis import SourceAnalysisService
from cintel.application.reports import ReportService
from cintel.application.scanning import RepositoryScanService
from cintel.configuration.models import AppConfig
from cintel.utilities.paths import stable_repository_id


class ReportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.repository_root = self.root / "repo"
        self.repository_root.mkdir()
        (self.repository_root / "main.c").write_text(
            '#include "util.h"\n'
            "\n"
            "int run(int value) {\n"
            "    return helper(value);\n"
            "}\n",
            encoding="utf-8",
        )
        (self.repository_root / "util.c").write_text(
            "int helper(int value) { return value + 1; }\n",
            encoding="utf-8",
        )
        (self.repository_root / "util.h").write_text(
            "int helper(int value);\n",
            encoding="utf-8",
        )
        self.output = self.root / "state"
        self.app_config = AppConfig(
            repository_root=str(self.repository_root),
            output_directory=str(self.output),
            database_path=str(self.output / "index.sqlite"),
        )

    def _service(self) -> ReportService:
        scanner = RepositoryScanService(
            discovery=FileSystemRepositoryDiscovery(),
            markdown_renderer=MarkdownReportRenderer(),
            json_renderer=JSONReportRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        )
        return ReportService(
            scanner=scanner,
            markdown_renderer=MarkdownReportRenderer(),
            json_renderer=JSONReportRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        )

    def _analyze(self) -> None:
        scanner = RepositoryScanService(
            discovery=FileSystemRepositoryDiscovery(),
            markdown_renderer=MarkdownReportRenderer(),
            json_renderer=JSONReportRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        )
        SourceAnalysisService(
            parser=ConservativeCSourceParser(),
            scanner=scanner,
            storage_factory=SQLiteAnalysisStorage,
        ).analyze(self.app_config)

    def test_generates_every_family_in_both_formats(self) -> None:
        self._analyze()
        result = self._service().generate_all(self.app_config)

        self.assertEqual((), result.diagnostics)
        names = {report.report_name for report in result.reports}
        self.assertEqual(
            {
                "repository_inventory",
                "build_selection",
                "compilation_units",
                "function_index",
                "symbol_index",
                "call_graph",
                "include_index",
                "global_usage",
                "diagnostics_index",
                "capability_index",
            },
            names,
        )
        for report in result.reports:
            self.assertTrue(Path(report.path).is_file(), report.path)

        call_graph = (
            self.output / "reports" / "call_graph.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"caller": "run"', call_graph)
        self.assertIn('"callee": "helper"', call_graph)
        self.assertIn('"resolution": "confirmed_direct"', call_graph)

        function_index = (
            self.output / "reports" / "function_index.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"definition_count": 2', function_index)

        include_index = (
            self.output / "reports" / "include_index.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"included_spelling": "util.h"', include_index)
        self.assertIn('"resolved_path": "util.h"', include_index)

        inventory = json.loads(
            (self.output / "reports" / "repository.json").read_text(
                encoding="utf-8"
            )
        )
        # main.c, util.c, and util.h all receive analysis results.
        self.assertEqual(3, inventory["build"]["analyzed_file_count"])

    def test_reports_are_deterministic_across_runs(self) -> None:
        self._analyze()
        first = self._service().generate_all(self.app_config)
        # The repository inventory embeds the scan timestamp by design; every
        # stored-state-derived family must be byte-identical across runs.
        first_contents = {
            report.path: Path(report.path).read_text(encoding="utf-8")
            for report in first.reports
            if report.report_name != "repository_inventory"
        }
        second = self._service().generate_all(self.app_config)
        for report in second.reports:
            if report.report_name == "repository_inventory":
                continue
            self.assertEqual(
                first_contents[report.path],
                Path(report.path).read_text(encoding="utf-8"),
                report.path,
            )

    def test_reports_record_workflow_state_and_metadata(self) -> None:
        from cintel.domain.models import WorkflowStage, WorkflowStatus

        self._analyze()
        self._service().generate_all(self.app_config)

        storage = SQLiteAnalysisStorage(Path(self.app_config.database_path))
        storage.initialize()
        try:
            states = storage.list_workflow_states(
                next(iter([stable_repository_id(self.repository_root)]))
            )
            report_states = [
                state for state in states if state.stage is WorkflowStage.REPORT
            ]
            self.assertEqual(1, len(report_states))
            self.assertIs(WorkflowStatus.COMPLETED, report_states[0].status)
            metadata = storage._connect().execute(
                "SELECT COUNT(*) FROM generated_reports"
            ).fetchone()[0]
            self.assertGreaterEqual(metadata, 16)
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
