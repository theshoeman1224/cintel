import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.build import MakeBuildDiscovery
from cintel.adapters.compiler import GCCCompilerCommandParser
from cintel.cli.main import main as cintel_main
from cintel.domain.models import BuildConfiguration, CommandRequest, CommandResult
from cintel.utilities.hashing import stable_id


FIXTURE = Path(__file__).parents[1] / "fixtures" / "complex_c_project"


class SavedOutputRunner:
    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, request: CommandRequest) -> CommandResult:
        return CommandResult(
            standard_output=self.output,
            standard_error="",
            exit_code=0,
            duration_seconds=0.1,
            executed_command=request.arguments,
            effective_working_directory=request.working_directory,
        )


class ComplexFixtureIntegrationTests(unittest.TestCase):
    def test_saved_linux_dry_run_exercises_parser_without_external_tools(self) -> None:
        sample = (
            FIXTURE / "expected/sample_inputs/make-linux-dry-run.txt"
        ).read_text(encoding="utf-8").replace("<FIXTURE_ROOT>", str(FIXTURE))
        repository_id = stable_id("repository", str(FIXTURE.resolve()))
        configuration = BuildConfiguration(
            id="fixture-linux",
            repository_id=repository_id,
            name="linux",
            repository_root=str(FIXTURE),
            makefile=str(FIXTURE / "Makefile"),
            working_directory=str(FIXTURE),
            target="linux",
        )
        result = MakeBuildDiscovery(
            SavedOutputRunner(sample), GCCCompilerCommandParser()
        ).discover(configuration)

        sources = {
            item.compiler_invocation.source.repository_relative
            for item in result.compilation_units
            if item.compiler_invocation.source is not None
        }
        self.assertIn("src/core/application.c", sources)
        self.assertIn("src/shared/checksum.c", sources)
        self.assertIn("src/plugins/plugin_alpha.c", sources)
        self.assertNotIn("src/legacy/unused_legacy_module.c", sources)
        self.assertGreaterEqual(len(result.compilation_units), 15)
        self.assertTrue(any(item.is_system for unit in result.compilation_units for item in unit.compiler_invocation.arguments.include_paths))

    @unittest.skipUnless(
        shutil.which("make") and shutil.which("gcc"),
        "GNU Make and GCC are required for the live fixture verification",
    )
    def test_fixture_builds_and_current_cintel_subset_validates(self) -> None:
        verification = subprocess.run(
            [sys.executable, "tools/verify_fixture.py"],
            cwd=FIXTURE,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        self.assertEqual(0, verification.returncode, verification.stdout + verification.stderr)

        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "analysis"
            with contextlib.redirect_stdout(io.StringIO()):
                scan_code = cintel_main(
                    [
                        "--repository",
                        str(FIXTURE),
                        "--output-directory",
                        str(output_directory),
                        "scan",
                    ]
                )
            self.assertEqual(0, scan_code)

            build_stdout = io.StringIO()
            with contextlib.redirect_stdout(build_stdout):
                build_code = cintel_main(
                    [
                        "--repository",
                        str(FIXTURE),
                        "--output-directory",
                        str(output_directory),
                        "--makefile",
                        "Makefile",
                        "--target",
                        "linux",
                        "--build-config",
                        "linux",
                        "--non-interactive",
                        "--force-build-discovery",
                        "--json",
                        "build",
                        "discover",
                    ]
                )
            self.assertEqual(0, build_code, build_stdout.getvalue())

            envelope = {
                "repository_report": json.loads(
                    (output_directory / "reports/repository.json").read_text(encoding="utf-8")
                ),
                "build_report": json.loads(build_stdout.getvalue()),
            }
            actual = Path(directory) / "actual.json"
            actual.write_text(json.dumps(envelope), encoding="utf-8")
            validation = subprocess.run(
                [
                    sys.executable,
                    str(FIXTURE / "tools/validate_cintel_results.py"),
                    "--expected",
                    str(FIXTURE / "expected/expected_findings.json"),
                    "--actual",
                    str(actual),
                    "--configuration",
                    "linux",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)
            self.assertIn("Unsupported:", validation.stdout)
            self.assertIn("Missing: 0", validation.stdout)


if __name__ == "__main__":
    unittest.main()
