import contextlib
import io
import json
import shutil
import sqlite3
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

    def test_phase_four_guidance_artifacts_resume_and_staleness(self) -> None:
        samples = FIXTURE / "expected" / "sample_inputs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "analysis"
            common = [
                "--repository", str(FIXTURE),
                "--output-directory", str(output),
                "--makefile", "Makefile",
                "--target", "linux",
                "--build-config", "linux",
                "--make-var", "API_TOKEN=fixture-secret",
                "--non-interactive",
            ]

            setup_output = io.StringIO()
            with contextlib.redirect_stdout(setup_output):
                self.assertEqual(0, cintel_main([*common, "setup"]))
            required = output / "REQUIRED_INPUTS.md"
            self.assertTrue(required.is_file())
            guidance = required.read_text(encoding="utf-8")
            self.assertIn("make -n -B", guidance)
            self.assertIn("make -n may still execute", guidance)
            self.assertIn("--input-file", guidance)
            self.assertNotIn("fixture-secret", guidance)
            self.assertIn("Preprocessed files may contain proprietary source", guidance)
            self.assertIn("must not be sent to an AI provider", guidance)

            instructions_output = io.StringIO()
            with contextlib.redirect_stdout(instructions_output):
                self.assertEqual(0, cintel_main([*common, "instructions"]))
            self.assertIn("Required-input report:", instructions_output.getvalue())
            json_output = io.StringIO()
            with contextlib.redirect_stdout(json_output):
                self.assertEqual(0, cintel_main([*common, "--json", "instructions"]))
            self.assertEqual("reduced", json.loads(json_output.getvalue())["status"])

            saved_build = io.StringIO()
            with contextlib.redirect_stdout(saved_build):
                saved_code = cintel_main(
                    [
                        *common,
                        "--input-file", str(samples / "make-linux-dry-run.txt"),
                        "build", "discover",
                    ]
                )
            self.assertEqual(0, saved_code, saved_build.getvalue())
            self.assertIn("Compilation units:", saved_build.getvalue())

            inputs = {
                "build_log": "verbose-build.log",
                "file_list": "repository-files.txt",
                "dependency_file": "application.d",
                "preprocessed_source": "application.i",
                "macro_listing": "macros.txt",
            }
            for artifact_type, filename in inputs.items():
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    code = cintel_main(
                        [
                            *common,
                            "--input-type", artifact_type,
                            "--input-file", str(samples / filename),
                            "resume",
                        ]
                    )
                self.assertEqual(0, code, captured.getvalue())

            units = io.StringIO()
            with contextlib.redirect_stdout(units):
                self.assertEqual(
                    0,
                    cintel_main(
                        [
                            "--repository", str(FIXTURE),
                            "--output-directory", str(output),
                            "--build-config", "linux",
                            "build", "units",
                        ]
                    ),
                )
            self.assertIn("src/core/application.c", units.getvalue())

            invalid = root / "empty-make-output.txt"
            invalid.write_text("", encoding="utf-8")
            invalid_output = io.StringIO()
            with contextlib.redirect_stdout(invalid_output):
                invalid_code = cintel_main(
                    [*common, "--input-file", str(invalid), "resume"]
                )
            self.assertEqual(2, invalid_code)
            self.assertIn("CI-INPUT-002", invalid_output.getvalue())

            connection = sqlite3.connect(output / "index.sqlite")
            rows = connection.execute(
                "SELECT artifact_type, validation_status, file_path FROM input_artifacts"
            ).fetchall()
            self.assertEqual(7, len(rows))
            persisted_text = "\n".join(
                row[0] for row in connection.execute("SELECT payload FROM input_artifacts")
            )
            self.assertNotIn("fixture-secret", persisted_text)
            self.assertIn("***REDACTED***", persisted_text)
            valid_make = next(
                Path(path)
                for artifact_type, validation, path in rows
                if artifact_type == "make_dry_run" and validation == "valid"
            )
            self.assertGreaterEqual(
                connection.execute("SELECT COUNT(*) FROM workflow_state").fetchone()[0],
                3,
            )
            connection.close()

            valid_make.write_text("modified after import\n", encoding="utf-8")
            stale_output = io.StringIO()
            with contextlib.redirect_stdout(stale_output):
                stale_code = cintel_main([*common, "resume"])
            self.assertEqual(0, stale_code)
            self.assertIn("CI-INPUT-003", stale_output.getvalue())
            self.assertIn("Recovery status: reduced", stale_output.getvalue())

    def test_phase_four_missing_generated_input_produces_exact_guidance(self) -> None:
        sample = FIXTURE / "expected/sample_inputs/make-missing-input-dry-run.txt"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis"
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = cintel_main(
                    [
                        "--repository", str(FIXTURE),
                        "--output-directory", str(output),
                        "--makefile", "Makefile",
                        "--target", "missing-input-demo",
                        "--build-config", "missing-input",
                        "--input-file", str(sample),
                        "--non-interactive",
                        "resume",
                    ]
                )
            self.assertEqual(0, code, captured.getvalue())
            self.assertIn("Recovery status: reduced", captured.getvalue())
            self.assertIn("CI-BUILD-005", captured.getvalue())
            report = (output / "REQUIRED_INPUTS.md").read_text(encoding="utf-8")
            self.assertIn("external_site_config.h", report)
            self.assertIn("find . -name external_site_config.h -print", report)
            self.assertIn("Do not run an unknown generation target", report)

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

            analysis_stdout = io.StringIO()
            with contextlib.redirect_stdout(analysis_stdout):
                analyze_code = cintel_main(
                    [
                        "--repository",
                        str(FIXTURE),
                        "--output-directory",
                        str(output_directory),
                        "--build-config",
                        "linux",
                        "analyze",
                    ]
                )
            self.assertEqual(0, analyze_code, analysis_stdout.getvalue())

            with contextlib.redirect_stdout(io.StringIO()):
                report_code = cintel_main(
                    [
                        "--repository",
                        str(FIXTURE),
                        "--output-directory",
                        str(output_directory),
                        "report",
                    ]
                )
            self.assertEqual(0, report_code)

            def load_report(name: str) -> dict:
                file_name = (
                    "repository.json" if name == "repository_inventory" else f"{name}.json"
                )
                return json.loads(
                    (output_directory / "reports" / file_name).read_text(
                        encoding="utf-8"
                    )
                )

            envelope = {
                "repository_report": load_report("repository_inventory"),
                "build_report": json.loads(build_stdout.getvalue()),
                "analysis_report": {
                    "symbol_index": load_report("symbol_index"),
                    "call_graph": load_report("call_graph"),
                    "include_index": load_report("include_index"),
                    "global_usage": load_report("global_usage"),
                },
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
