import tempfile
import unittest
from pathlib import Path

from cintel.application.doctor import DoctorService
from cintel.configuration.loader import default_config
from cintel.domain.models import CommandRequest, CommandResult


class SuccessfulFakeRunner:
    def run(self, request: CommandRequest) -> CommandResult:
        return CommandResult(
            standard_output=f"{Path(request.arguments[0]).name} version 1\n",
            standard_error="",
            exit_code=0,
            duration_seconds=0.01,
            executed_command=request.arguments,
            effective_working_directory=request.working_directory,
        )


class DoctorTests(unittest.TestCase):
    def test_detects_phase_one_repository_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            (root / "compile_commands.json").write_text("[]", encoding="utf-8")
            (root / "old.o").write_bytes(b"")
            report = DoctorService(SuccessfulFakeRunner()).inspect(default_config(root))

            self.assertEqual(("Makefile",), report.detected_inputs["makefiles"])
            self.assertEqual(("old.o",), report.detected_inputs["object_files"])
            self.assertEqual(
                ("compile_commands.json",), report.detected_inputs["compile_databases"]
            )
            self.assertTrue(report.output_directory_writable)
            self.assertTrue(any(item.name == "ai_generation" for item in report.capabilities))

    def test_missing_makefile_is_structured_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = DoctorService(SuccessfulFakeRunner()).inspect(
                default_config(Path(directory))
            )
            self.assertIn("CI-BUILD-002", {item.code for item in report.diagnostics})

    def test_missing_repository_is_structured_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-present"
            report = DoctorService(SuccessfulFakeRunner()).inspect(default_config(missing))
            self.assertIn("CI-REPO-001", {item.code for item in report.diagnostics})
