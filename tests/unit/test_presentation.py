import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cintel.cli.presentation import (
    render_build_discovery,
    render_compilation_units,
    render_doctor,
    render_recovery,
)
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CapabilityStatus,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    DoctorReport,
    PathReference,
    RecoveryResult,
    ToolStatus,
    WorkflowStatus,
)


def _doctor_report() -> DoctorReport:
    return DoctorReport(
        repository_root="/repo",
        python_version="3.11.4",
        tools=(
            ToolStatus(name="make", path="/usr/bin/make", version="GNU Make 4.3", available=True),
            ToolStatus(name="gcc", path=None, version=None, available=False),
        ),
        output_directory_writable=True,
        detected_inputs={"makefiles": ("Makefile",)},
        capabilities=(
            AnalysisCapability(
                name="make_build_discovery",
                status=CapabilityStatus.AVAILABLE,
                reason="GNU Make is available.",
            ),
        ),
        diagnostics=(
            Diagnostic(
                code="CI-COMP-001",
                severity=DiagnosticSeverity.WARNING,
                message="GCC was not found.",
                suggested_actions=("Install GCC or continue without it.",),
            ),
        ),
        recommended_actions=("Run `cintel init <repository>` to create the local workspace.",),
    )


def _build_result() -> BuildDiscoveryResult:
    configuration = BuildConfiguration(
        id="build-1",
        repository_id="repository-1",
        name="linux",
        repository_root="/repo",
        makefile="/repo/Makefile",
        working_directory="/repo",
    )
    invocation = CompilerInvocation(
        id="invocation-1",
        compiler_executable="gcc",
        launchers=(),
        source=PathReference(original="main.c", absolute="/repo/main.c", repository_relative="main.c"),
        object_file=None,
        working_directory="/repo",
        raw_command="gcc -c main.c",
        raw_arguments=("-c", "main.c"),
        arguments=CompilerArgumentSet(unclassified_arguments=("-c",)),
    )
    unit = CompilationUnit(
        id="unit-1",
        repository_id="repository-1",
        build_configuration_id="build-1",
        source_file_id=None,
        compiler_invocation=invocation,
        fingerprint="unit-fingerprint",
    )
    return BuildDiscoveryResult(
        configuration=configuration,
        make_arguments=("make", "-n", "-B"),
        raw_output="",
        raw_error="",
        exit_code=0,
        duration_seconds=0.25,
        commands=(),
        compiler_invocations=(invocation,),
        compilation_units=(unit,),
        diagnostics=(
            Diagnostic(
                code="CI-BUILD-004",
                severity=DiagnosticSeverity.WARNING,
                message="A compiler command references a missing source file.",
            ),
        ),
        capabilities=(),
        input_fingerprint="input-fingerprint",
        build_fingerprint="build-fingerprint",
        discovered_at=datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc),
    )


def _recovery_result() -> RecoveryResult:
    return RecoveryResult(
        repository_id="repository-1",
        status=WorkflowStatus.REDUCED,
        artifacts=(),
        diagnostics=(
            Diagnostic(
                code="CI-INPUT-001",
                severity=DiagnosticSeverity.WARNING,
                message="Build discovery evidence is not available yet.",
            ),
        ),
        instructions=(),
        capabilities=(),
        completed_stages=("repository_scan",),
        interrupted_stage=None,
        required_inputs_report="/repo/.code-intelligence/REQUIRED_INPUTS.md",
    )


class PresentationTests(unittest.TestCase):
    def test_doctor_text_lists_tools_capabilities_and_diagnostics(self) -> None:
        text = render_doctor(_doctor_report())
        self.assertIn("Legacy C Code Intelligence doctor", text)
        self.assertIn("make: available — GNU Make 4.3", text)
        self.assertIn("gcc: unavailable", text)
        self.assertIn("make_build_discovery: available — GNU Make is available.", text)
        self.assertIn("[CI-COMP-001] warning: GCC was not found.", text)
        self.assertIn("- Run `cintel init <repository>`", text)

    def test_doctor_json_round_trips_key_fields(self) -> None:
        payload = json.loads(render_doctor(_doctor_report(), as_json=True))
        self.assertEqual("/repo", payload["repository_root"])
        self.assertTrue(payload["output_directory_writable"])
        self.assertEqual(2, len(payload["tools"]))
        self.assertEqual("warning", payload["diagnostics"][0]["severity"])

    def test_build_discovery_text_reports_counts_and_source(self) -> None:
        text = render_build_discovery(_build_result())
        self.assertIn("Build configuration: linux", text)
        self.assertIn("Make command: make -n -B", text)
        self.assertIn("Compilation units: 1", text)
        self.assertIn("[CI-BUILD-004]", text)
        self.assertIn("Source: Make dry-run", text)

    def test_cached_build_discovery_text_reports_cache_source(self) -> None:
        result = replace(_build_result(), from_cache=True)
        text = render_build_discovery(result)
        self.assertIn("Source: cache", text)

    def test_compilation_units_text_and_empty_case(self) -> None:
        units = _build_result().compilation_units
        text = render_compilation_units(units)
        self.assertIn("main.c", text)
        self.assertIn("Compiler: gcc", text)
        self.assertEqual("No compilation units found.", render_compilation_units(()))

    def test_recovery_text_reports_status_stages_and_diagnostics(self) -> None:
        text = render_recovery(_recovery_result())
        self.assertIn("Recovery status: reduced", text)
        self.assertIn("Completed stages: repository_scan", text)
        self.assertIn("[CI-INPUT-001] warning:", text)
        self.assertIn("REQUIRED_INPUTS.md", text)

    def test_recovery_json_round_trips_status_and_stages(self) -> None:
        payload = json.loads(render_recovery(_recovery_result(), as_json=True))
        self.assertEqual("reduced", payload["status"])
        self.assertEqual(["repository_scan"], payload["completed_stages"])
        self.assertIsNone(payload["interrupted_stage"])

    def test_json_renderings_are_deterministic(self) -> None:
        first = render_build_discovery(_build_result(), as_json=True)
        second = render_build_discovery(_build_result(), as_json=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
