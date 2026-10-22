import tempfile
import unittest
from pathlib import Path

from cintel.application.doctor import DoctorService
from cintel.configuration.loader import default_config
from cintel.domain.models import (
    CapabilityStatus,
    CommandRequest,
    CommandResult,
)


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


class UnavailableFakeRunner:
    def run(self, request: CommandRequest) -> CommandResult:
        return CommandResult(
            standard_output="",
            standard_error=f"{Path(request.arguments[0]).name}: not found",
            exit_code=127,
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
            self.assertTrue(
                any(item.name == "guided_input_recovery" for item in report.capabilities)
            )

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

    def test_missing_tools_report_reduced_capabilities_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            report = DoctorService(UnavailableFakeRunner()).inspect(
                default_config(root)
            )
        codes = {item.code for item in report.diagnostics}
        self.assertIn("CI-BUILD-001", codes)
        self.assertIn("CI-COMP-001", codes)

        make_capability = next(
            item for item in report.capabilities if item.name == "make_build_discovery"
        )
        gcc_capability = next(
            item for item in report.capabilities if item.name == "gcc_enrichment"
        )
        self.assertEqual(CapabilityStatus.UNAVAILABLE, make_capability.status)
        self.assertEqual(CapabilityStatus.UNAVAILABLE, gcc_capability.status)

        make_status = next(item for item in report.tools if item.name == "make")
        self.assertFalse(make_status.available)
        self.assertTrue(
            any("cintel setup" in action for action in report.recommended_actions)
        )

    def test_recommends_init_only_without_a_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
            config = default_config(root)
            service = DoctorService(SuccessfulFakeRunner())

            report = service.inspect(config)
            self.assertTrue(
                any("cintel init" in item for item in report.recommended_actions)
            )

            output = Path(config.output_directory)
            output.mkdir(parents=True)
            (output / "config.toml").write_text("", encoding="utf-8")
            report = service.inspect(config)
            self.assertFalse(
                any("cintel init" in item for item in report.recommended_actions)
            )
            self.assertTrue(
                any("cintel" in item and "scan" in item for item in report.recommended_actions)
            )

    def test_gcc_enrichment_is_not_claimed_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = DoctorService(SuccessfulFakeRunner()).inspect(
                default_config(Path(directory))
            )
        gcc_tool = next(item for item in report.tools if item.name == "gcc")
        self.assertTrue(gcc_tool.available)
        capability = next(
            item for item in report.capabilities if item.name == "gcc_enrichment"
        )
        self.assertEqual(CapabilityStatus.UNAVAILABLE, capability.status)
        self.assertIn("not implemented", capability.reason)

