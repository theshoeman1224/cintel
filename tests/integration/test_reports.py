import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cintel.cli.main import main


class ReportCommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.workspace = Path(self._temporary.name) / "repo"
        fixture = Path(__file__).parents[1] / "fixtures" / "repositories" / "basic"
        shutil.copytree(fixture, self.workspace)
        self._run("init", str(self.workspace))
        self._run("--repository", str(self.workspace), "scan")
        self._run("--repository", str(self.workspace), "analyze")

    def _run(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(arguments))
        return code, output.getvalue()

    def test_report_generates_all_families(self) -> None:
        code, text = self._run("--repository", str(self.workspace), "report")
        self.assertEqual(0, code)
        reports_directory = self.workspace / ".code-intelligence" / "reports"
        expected = [
            "build_selection.md",
            "build_selection.json",
            "compilation_units.md",
            "compilation_units.json",
            "function_index.md",
            "function_index.json",
            "call_graph.md",
            "call_graph.json",
            "include_index.md",
            "include_index.json",
            "diagnostics_index.md",
            "diagnostics_index.json",
            "capability_index.md",
            "capability_index.json",
        ]
        for name in expected:
            self.assertTrue((reports_directory / name).is_file(), name)
        self.assertIn("repository_inventory [markdown]", text)
        self.assertIn("call_graph [json]", text)

    def test_report_json_output_is_machine_readable(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace), "--json", "report"
        )
        self.assertEqual(0, code)
        payload = json.loads(text)
        names = {report["report_name"] for report in payload["reports"]}
        self.assertIn("call_graph", names)
        self.assertEqual((), tuple(payload["diagnostics"]))

    def test_report_integrates_build_state_into_inventory(self) -> None:
        self._run("--repository", str(self.workspace), "report")
        inventory = json.loads(
            (
                self.workspace
                / ".code-intelligence"
                / "reports"
                / "repository.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(0, inventory["build"]["compilation_unit_count"])
        self.assertEqual(
            "unavailable_information", inventory["build"]["classification"]
        )

    def test_report_metadata_records_families(self) -> None:
        self._run("--repository", str(self.workspace), "report")
        call_graph = json.loads(
            (
                self.workspace
                / ".code-intelligence"
                / "reports"
                / "call_graph.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("main", [edge["caller"] for edge in call_graph["edges"]])
        self.assertIn(
            "project_value", [edge["callee"] for edge in call_graph["edges"]]
        )


if __name__ == "__main__":
    unittest.main()
