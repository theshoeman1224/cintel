import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cintel.cli.main import main as cintel_main


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
            self.assertGreaterEqual(analyzed["entry_points"], 1)

            forced = json.loads(
                self._run([*common, "--json", "analyze", "--force-analysis"])
            )
            self.assertEqual(0, forced["reused_results"])

    @staticmethod
    def _run(arguments: list[str]) -> str:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exit_code = cintel_main(arguments)
        assert exit_code == 0, captured.getvalue()
        return captured.getvalue()


if __name__ == "__main__":
    unittest.main()
