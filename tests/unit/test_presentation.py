import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from cintel.application.context import ContextResult
from cintel.application.initialization import InitializationResult
from cintel.application.queries import (
    CallSite,
    FunctionCandidates,
    FunctionDetail,
    SymbolEntry,
    SymbolsResult,
)
from cintel.application.reports import GeneratedReport, ReportRunResult
from cintel.application.scanning import ScanWorkflowResult
from cintel.cli.presentation import (
    _json,
    _json_default,
    render_analysis,
    render_build_discovery,
    render_call_sites,
    render_compilation_units,
    render_context_result,
    render_doctor,
    render_function_detail,
    render_initialization,
    render_recovery,
    render_report_run,
    render_scan,
    render_symbols,
)
from cintel.configuration.models import AppConfig
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import (
    AnalysisCapability,
    AnalysisRunSummary,
    BuildConfiguration,
    BuildDiscoveryResult,
    CapabilityStatus,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    ContextPackage,
    DoctorReport,
    FileKind,
    PathReference,
    RecoveryResult,
    Repository,
    RepositoryFile,
    RepositoryScan,
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
        discovered_at=datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC),
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


def _analysis_summary() -> AnalysisRunSummary:
    return AnalysisRunSummary(
        repository_id="repository-1",
        build_configuration_name="linux",
        files_selected=4,
        units_selected=3,
        reused_results=1,
        stored_results=3,
        failed_results=0,
        resolved_calls=9,
        unresolved_calls=2,
        resolved_includes=11,
        unresolved_includes=1,
        entry_points=1,
        unreachable_definitions=3,
        recursive_functions=("perform_retry_sequence",),
        status=WorkflowStatus.COMPLETED,
        capabilities=(),
        diagnostics=(),
    )


def _symbol_entry(
    name: str = "project_value",
    *,
    kind: str = "function",
    is_definition: bool = True,
    linkage: str | None = "external",
    relative_path: str = "src/main.c",
    line: int = 10,
) -> SymbolEntry:
    return SymbolEntry(
        symbol_id=f"symbol-{name}-{line}",
        name=name,
        kind=kind,
        relative_path=relative_path,
        line=line,
        end_line=line + 2,
        is_definition=is_definition,
        linkage=linkage,
        detail="int project_value(void)",
        analysis_id="analysis-1",
        compilation_unit_id=None,
    )


def _call_site(
    name: str, relative_path: str, line: int, resolution: str
) -> CallSite:
    return CallSite(
        function_name=name,
        relative_path=relative_path,
        line=line,
        resolution=resolution,
    )


def _repository() -> Repository:
    return Repository(
        id="repository-1",
        root="/repo",
        name="repo",
        created_at=datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC),
    )


def _initialization_result() -> InitializationResult:
    return InitializationResult(
        config=AppConfig(
            repository_root="/repo",
            output_directory="/repo/.code-intelligence",
            database_path="/repo/.code-intelligence/index.sqlite",
        ),
        repository=_repository(),
        created_paths=("input", "cache", "reports"),
        existing_paths=("/repo/.code-intelligence",),
    )


def _scan_result() -> ScanWorkflowResult:
    return ScanWorkflowResult(
        scan=RepositoryScan(
            repository=_repository(),
            files=(
                RepositoryFile(
                    id="file-1",
                    repository_id="repository-1",
                    relative_path="src/main.c",
                    absolute_path="/repo/src/main.c",
                    kind=FileKind.C_SOURCE,
                    size=120,
                    modified_at=datetime(2026, 8, 22, 11, 0, 0, tzinfo=UTC),
                    content_sha256="a" * 64,
                ),
            ),
            diagnostics=(
                Diagnostic(
                    code="CI-REPO-004",
                    severity=DiagnosticSeverity.WARNING,
                    message="A source symlink was skipped.",
                    suggested_actions=("Inspect the symlink manually.",),
                ),
            ),
            capabilities=(),
            scanned_at=datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC),
            hashes_computed=1,
            hashes_reused=0,
        ),
        markdown_report="/repo/.code-intelligence/repository.md",
        json_report="/repo/.code-intelligence/reports/repository.json",
    )


def _function_detail() -> FunctionDetail:
    return FunctionDetail(
        repository_id="repository-1",
        definition=_symbol_entry(),
        declarations=(
            _symbol_entry(
                is_definition=False,
                linkage=None,
                relative_path="include/project.h",
                line=4,
            ),
        ),
        callers=(_call_site("main", "src/main.c", 22, "resolved"),),
        callees=(
            _call_site("helper", "src/util.c", 8, "resolved"),
            _call_site("missing", "src/main.c", 30, "unresolved"),
        ),
    )


def _candidates() -> FunctionCandidates:
    return FunctionCandidates(
        name="project_value",
        candidates=(
            _symbol_entry(relative_path="src/a.c", line=5),
            _symbol_entry(relative_path="src/b.c", line=9),
        ),
    )


def _context_result() -> ContextResult:
    package = ContextPackage(
        function_id="symbol-project_value-10",
        title="project_value",
        sections=(
            ("Definition excerpt", "int project_value(void) { return 1; }"),
            ("Callers", "main at src/main.c:22"),
        ),
        character_budget=8000,
        used_characters=120,
        capabilities=(
            AnalysisCapability(
                name="deterministic_context",
                status=CapabilityStatus.AVAILABLE,
                reason="Static state produced the package.",
            ),
        ),
        evidence=(),
    )
    return ContextResult(
        package=package,
        output_path="/repo/.code-intelligence/context/project_value__src_main.c.md",
    )


def _report_run() -> ReportRunResult:
    return ReportRunResult(
        repository_id="repository-1",
        reports=(
            GeneratedReport(
                report_name="call_graph",
                format="markdown",
                path="/repo/.code-intelligence/reports/call_graph.md",
            ),
            GeneratedReport(
                report_name="call_graph",
                format="json",
                path="/repo/.code-intelligence/reports/call_graph.json",
            ),
        ),
        diagnostics=(
            Diagnostic(
                code="CI-GEN-001",
                severity=DiagnosticSeverity.ERROR,
                message="include_index generation failed.",
            ),
        ),
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

    def test_analysis_text_reports_calls_and_includes_including_unresolved(self) -> None:
        text = render_analysis(_analysis_summary())
        self.assertIn("Source analysis: completed", text)
        self.assertIn("Calls: 9 resolved, 2 unresolved", text)
        self.assertIn("Includes: 11 resolved, 1 unresolved", text)
        self.assertIn("unreachable definitions: 3", text)

    def test_analysis_json_round_trips_key_fields(self) -> None:
        payload = json.loads(render_analysis(_analysis_summary(), as_json=True))
        self.assertEqual("linux", payload["build_configuration_name"])
        self.assertEqual(11, payload["resolved_includes"])
        self.assertEqual(1, payload["unresolved_includes"])
        self.assertEqual(2, payload["unresolved_calls"])

    def test_json_renderings_are_deterministic(self) -> None:
        first = render_build_discovery(_build_result(), as_json=True)
        second = render_build_discovery(_build_result(), as_json=True)
        self.assertEqual(first, second)

    def test_initialization_text_reports_paths_and_next_step(self) -> None:
        text = render_initialization(_initialization_result())
        self.assertIn("Initialized Legacy C Code Intelligence for /repo", text)
        self.assertIn(
            "Configuration: /repo/.code-intelligence/config.toml", text
        )
        self.assertIn("Database: /repo/.code-intelligence/index.sqlite", text)
        self.assertIn("Created 3 path(s).", text)
        self.assertIn("Reused 1 existing path(s).", text)
        self.assertIn("Next: run `cintel --repository <path> doctor`.", text)

    def test_initialization_text_omits_empty_path_sections(self) -> None:
        result = replace(
            _initialization_result(), created_paths=(), existing_paths=()
        )
        text = render_initialization(result)
        self.assertNotIn("Created", text)
        self.assertNotIn("Reused", text)

    def test_initialization_json_round_trips_paths(self) -> None:
        payload = json.loads(render_initialization(_initialization_result(), as_json=True))
        self.assertEqual("/repo", payload["repository"]["root"])
        self.assertEqual(["input", "cache", "reports"], payload["created_paths"])

    def test_scan_text_reports_counts_reports_and_diagnostics(self) -> None:
        text = render_scan(_scan_result())
        self.assertIn("Scanned /repo", text)
        self.assertIn("Relevant files: 1", text)
        self.assertIn("SHA-256 hashes: 1 computed, 0 reused", text)
        self.assertIn(
            "Markdown report: /repo/.code-intelligence/repository.md", text
        )
        self.assertIn(
            "JSON report: /repo/.code-intelligence/reports/repository.json", text
        )
        self.assertIn("[CI-REPO-004] warning: A source symlink was skipped.", text)

    def test_scan_text_without_reports_skips_report_lines(self) -> None:
        result = replace(_scan_result(), markdown_report=None, json_report=None)
        text = render_scan(result)
        self.assertNotIn("Markdown report", text)
        self.assertNotIn("JSON report", text)

    def test_scan_json_serializes_files_and_timestamps(self) -> None:
        payload = json.loads(render_scan(_scan_result(), as_json=True))
        self.assertEqual(1, payload["scan"]["hashes_computed"])
        self.assertEqual("src/main.c", payload["scan"]["files"][0]["relative_path"])
        self.assertEqual(
            "c_source", payload["scan"]["files"][0]["kind"]
        )
        self.assertTrue(payload["scan"]["scanned_at"].startswith("2026-08-22T12:00:00"))

    def test_symbols_text_lists_entries_and_handles_empty_results(self) -> None:
        result = SymbolsResult(
            repository_id="repository-1",
            entries=(
                _symbol_entry(),
                _symbol_entry(name="helper", relative_path="src/util.c", line=30),
            ),
        )
        text = render_symbols(result)
        self.assertIn("Symbols: 2", text)
        self.assertIn(
            "function project_value [definition] src/main.c:10 int project_value(void)",
            text,
        )
        self.assertEqual("No symbols found.", render_symbols(SymbolsResult("repository-1", ())))

    def test_symbols_json_round_trips_entries(self) -> None:
        result = SymbolsResult("repository-1", (_symbol_entry(),))
        payload = json.loads(render_symbols(result, as_json=True))
        self.assertEqual("project_value", payload["entries"][0]["name"])
        self.assertTrue(payload["entries"][0]["is_definition"])

    def test_function_detail_text_reports_relationships_and_declarations(self) -> None:
        text = render_function_detail(_function_detail())
        self.assertIn("Function: project_value", text)
        self.assertIn("Location: src/main.c:10", text)
        self.assertIn("Kind: definition (external linkage)", text)
        self.assertIn("Signature: int project_value(void)", text)
        self.assertIn("Callers: 1", text)
        self.assertIn("  main (resolved) at src/main.c:22", text)
        self.assertIn("Callees: 2", text)
        self.assertIn("  missing (unresolved) at src/main.c:30", text)
        self.assertIn("Declarations:", text)
        self.assertIn("include/project.h:4", text)

    def test_function_detail_text_reports_empty_relationships(self) -> None:
        result = replace(
            _function_detail(), callers=(), callees=(), declarations=()
        )
        text = render_function_detail(result)
        self.assertIn("Callers: none", text)
        self.assertIn("Callees: none", text)
        self.assertNotIn("Declarations:", text)

    def test_function_candidates_text_lists_every_definition(self) -> None:
        text = render_function_detail(_candidates())
        self.assertIn(
            "Ambiguous function name: project_value (2 definitions); "
            "rerun with --file to choose one.",
            text,
        )
        self.assertIn("src/a.c:5", text)
        self.assertIn("src/b.c:9", text)

    def test_call_sites_text_lists_edges_and_handles_empty_results(self) -> None:
        sites = (_call_site("main", "src/main.c", 22, "resolved"),)
        text = render_call_sites("project_value", sites)
        self.assertIn("Call relationships for project_value: 1", text)
        self.assertIn("  main (resolved) at src/main.c:22", text)
        self.assertEqual(
            "No call relationships found for project_value.",
            render_call_sites("project_value", ()),
        )

    def test_call_sites_json_round_trips_edges(self) -> None:
        sites = (_call_site("main", "src/main.c", 22, "resolved"),)
        payload = json.loads(render_call_sites("project_value", sites, as_json=True))
        self.assertEqual("main", payload[0]["function_name"])
        self.assertEqual("resolved", payload[0]["resolution"])

    def test_context_result_text_reports_budget_sections_and_capabilities(self) -> None:
        text = render_context_result(_context_result())
        self.assertIn(
            "Context package: /repo/.code-intelligence/context/"
            "project_value__src_main.c.md",
            text,
        )
        self.assertIn("Budget: 120 of 8000 characters", text)
        self.assertIn("Sections: 2", text)
        self.assertIn("  Definition excerpt (37 chars)", text)
        self.assertIn(
            "[available] deterministic_context: Static state produced the package.",
            text,
        )

    def test_context_candidates_report_ambiguity(self) -> None:
        text = render_context_result(_candidates())
        self.assertIn("Ambiguous function name: project_value", text)

    def test_report_run_text_lists_reports_and_failures(self) -> None:
        text = render_report_run(_report_run())
        self.assertIn("Reports generated: 2", text)
        self.assertIn(
            "  call_graph [markdown]: "
            "/repo/.code-intelligence/reports/call_graph.md",
            text,
        )
        self.assertIn("[CI-GEN-001] error: include_index generation failed.", text)

    def test_report_run_json_round_trips_reports_and_diagnostics(self) -> None:
        payload = json.loads(render_report_run(_report_run(), as_json=True))
        self.assertEqual("call_graph", payload["reports"][1]["report_name"])
        self.assertEqual("json", payload["reports"][1]["format"])
        self.assertEqual("error", payload["diagnostics"][0]["severity"])

    def test_json_serializes_an_empty_tuple_as_an_empty_list(self) -> None:
        self.assertEqual("[]", _json(()))

    def test_json_default_serializes_datetimes_and_enums(self) -> None:
        moment = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
        self.assertEqual("2026-08-22T12:00:00+00:00", _json_default(moment))
        self.assertEqual("available", _json_default(CapabilityStatus.AVAILABLE))

    def test_json_default_rejects_unknown_types(self) -> None:
        with self.assertRaises(TypeError) as caught:
            _json_default(object())
        self.assertIn("Cannot serialize object", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
