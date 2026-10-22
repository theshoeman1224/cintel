import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.analysis_scope import active_scope
from cintel.cli.main import main as cintel_main
from cintel.utilities.paths import stable_repository_id

FIXTURE = Path(__file__).parents[1] / "fixtures" / "complex_c_project"
BASIC = Path(__file__).parents[1] / "fixtures" / "repositories" / "basic"


class AnalysisWorkflowIntegrationTests(unittest.TestCase):
    def test_unconfigured_analysis_is_incremental_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis"
            common = ["--repository", str(BASIC), "--output-directory", str(output)]

            first_text = self._run([*common, "--json", "analyze"])
            second_text = self._run([*common, "--json", "analyze"])

            first = json.loads(first_text)
            second = json.loads(second_text)

            self.assertEqual("completed", first["status"])
            self.assertEqual(3, first["files_selected"])
            self.assertEqual(0, first["units_selected"])
            self.assertEqual(3, first["stored_results"])
            self.assertGreaterEqual(first["resolved_calls"], 1)
            self.assertGreaterEqual(first["unresolved_includes"], 1)

            self.assertEqual("completed", second["status"])
            self.assertEqual(3, second["reused_results"])
            self.assertEqual(0, second["stored_results"])

    def test_configured_analysis_uses_compilation_units_and_include_paths(self) -> None:
        sample = FIXTURE / "expected/sample_inputs/make-linux-dry-run.txt"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis"
            common = [
                "--repository", str(FIXTURE),
                "--output-directory", str(output),
                "--makefile", "Makefile",
                "--target", "linux",
                "--build-config", "linux",
                "--non-interactive",
            ]
            self._run(
                [
                    *common,
                    "--input-file", str(sample),
                    "build", "discover",
                ]
            )

            analyzed = json.loads(
                self._run([*common, "--json", "analyze"])
            )

            self.assertEqual("completed", analyzed["status"])
            self.assertEqual("linux", analyzed["build_configuration_name"])
            self.assertGreaterEqual(analyzed["units_selected"], 15)
            self.assertGreaterEqual(analyzed["resolved_includes"], 1)
            self.assertGreaterEqual(analyzed["unresolved_includes"], 1)
            self.assertGreaterEqual(analyzed["entry_points"], 1)

            forced = json.loads(
                self._run([*common, "--json", "analyze", "--force-analysis"])
            )
            self.assertEqual(0, forced["reused_results"])

    def test_queries_and_reports_follow_the_latest_analysis_scope(self) -> None:
        # A build-aware run followed by a plain (file-scoped) run used to
        # leave both result sets in storage, and queries and reports merged
        # them into contradictory edges for the same call site.
        sample = FIXTURE / "expected/sample_inputs/make-linux-dry-run.txt"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis"
            base = ["--repository", str(FIXTURE), "--output-directory", str(output)]
            linux = [*base, "--build-config", "linux"]
            self._run(
                [
                    *linux, "--makefile", "Makefile", "--target", "linux",
                    "--non-interactive", "--input-file", str(sample),
                    "build", "discover",
                ]
            )
            self._run([*linux, "analyze"])
            linux_callees = self._callees_of_main(base)
            self.assertEqual(
                {"confirmed_direct"}, linux_callees["platform_name"]
            )

            self._run([*base, "analyze"])
            self._assert_single_resolution_per_call(base, output)
            self._assert_resolved_calls_stay_in_scope(output)
            self.assertEqual(
                {"unresolved"}, self._callees_of_main(base)["platform_name"]
            )

            self._run([*linux, "analyze"])
            self._assert_single_resolution_per_call(base, output)
            self.assertEqual(linux_callees, self._callees_of_main(base))

    def _assert_resolved_calls_stay_in_scope(self, output: Path) -> None:
        # File-scoped results are shared by every run; a call they resolved
        # under another configuration must not keep pointing there.
        storage = SQLiteAnalysisStorage(output / "index.sqlite")
        storage.initialize()
        try:
            repository_id = stable_repository_id(str(FIXTURE))
            scope = active_scope(storage, repository_id)
            assert scope.analysis_ids is not None
            edges = scope.keep(storage.find_call_edges(repository_id))
            callee_ids = tuple(
                {edge.call.callee_id for edge in edges if edge.call.callee_id}
            )
            outside = [
                occurrence.symbol.name
                for occurrence in storage.get_symbols_by_ids(
                    repository_id, callee_ids
                )
                if occurrence.analysis_id not in scope.analysis_ids
            ]
            self.assertEqual([], outside)
        finally:
            storage.close()

    def _callees_of_main(self, base: list[str]) -> dict[str, set[str]]:
        payload = json.loads(
            self._run(
                [*base, "--json", "callees", "main", "--file", "src/app/main.c"]
            )
        )
        resolutions: dict[str, set[str]] = {}
        for entry in payload:
            resolutions.setdefault(entry["function_name"], set()).add(
                entry["resolution"]
            )
        return resolutions

    def _assert_single_resolution_per_call(
        self, base: list[str], output: Path
    ) -> None:
        for name, resolutions in self._callees_of_main(base).items():
            self.assertEqual(1, len(resolutions), f"{name}: {resolutions}")
        self._run([*base, "report"])
        graph = json.loads(
            (output / "reports" / "call_graph.json").read_text(encoding="utf-8")
        )
        seen: dict[tuple[str, str, int, str], str] = {}
        for edge in graph["edges"]:
            key = (
                edge["caller"],
                edge["caller_path"],
                edge["call_site_line"],
                edge["callee"],
            )
            self.assertNotIn(key, seen, f"duplicate edge for {key}")
            seen[key] = edge["resolution"]

    @staticmethod
    def _run(arguments: list[str]) -> str:
        captured = io.StringIO()
        diagnostics = io.StringIO()
        with (
            contextlib.redirect_stdout(captured),
            contextlib.redirect_stderr(diagnostics),
        ):
            exit_code = cintel_main(arguments)
        assert exit_code == 0, captured.getvalue()
        return captured.getvalue()


if __name__ == "__main__":
    unittest.main()
