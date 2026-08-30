import json
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
)
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildSelectionEntry,
    BuildSelectionReportData,
    CapabilityIndexReportData,
    CapabilityStatus,
    CallGraphEdge,
    CallGraphReportData,
    CompilationUnitEntry,
    CompilationUnitsReportData,
    DiagnosticsReportData,
    FunctionIndexEntry,
    FunctionIndexReportData,
    IncludeIndexEntry,
    IncludeIndexReportData,
    RepositoryReportData,
)
from cintel.utilities.hashing import stable_id


def _scan(root: Path, repository_id: str):
    (root / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    return FileSystemRepositoryDiscovery().discover(
        str(root), repository_id, ()
    )


def _report_data(scan) -> RepositoryReportData:
    return RepositoryReportData(
        scan=scan,
        build_configurations=(),
        compilation_unit_count=0,
        analyzed_file_count=0,
    )


class RepositoryReportTests(unittest.TestCase):
    def test_markdown_and_json_distinguish_evidence_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan = _scan(Path(directory), "repository-1")

            markdown = MarkdownReportRenderer().render(
                "repository_inventory", _report_data(scan)
            )
            payload = json.loads(
                JSONReportRenderer().render(
                    "repository_inventory", _report_data(scan)
                )
            )

            self.assertIn("extracted fact", markdown)
            self.assertIn("calculated metric", markdown)
            self.assertIn("unavailable information", markdown)
            self.assertEqual("calculated_metric", payload["metrics"]["classification"])
            self.assertEqual("extracted_fact", payload["files"][0]["classification"])

    def test_markdown_labels_build_awareness_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan = _scan(Path(directory), "repository-1")

            markdown = MarkdownReportRenderer().render(
                "repository_inventory", _report_data(scan)
            )

        self.assertIn("No persisted build discoveries", markdown)
        self.assertIn("`cintel build discover`", markdown)
        self.assertNotIn("until Phase 3", markdown)

    def test_markdown_integrates_persisted_build_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan = _scan(Path(directory), "repository-1")
            configuration = BuildConfiguration(
                id=stable_id("build", "repository-1", "debug"),
                repository_id="repository-1",
                name="debug",
                repository_root=str(directory),
                target="all",
            )
            data = RepositoryReportData(
                scan=scan,
                build_configurations=(configuration,),
                compilation_unit_count=3,
                analyzed_file_count=2,
            )

            markdown = MarkdownReportRenderer().render("repository_inventory", data)
            payload = json.loads(JSONReportRenderer().render(
                "repository_inventory", data
            ))

        self.assertIn("Persisted build configurations: 1", markdown)
        self.assertIn("Compilation units recorded: 3", markdown)
        self.assertIn("debug", markdown)
        self.assertEqual(3, payload["build"]["compilation_unit_count"])
        self.assertEqual(["debug"], payload["build"]["build_configurations"])
        self.assertEqual("extracted_fact", payload["build"]["classification"])

    def test_unknown_report_names_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MarkdownReportRenderer().render("unknown", {})
        with self.assertRaises(ValueError):
            JSONReportRenderer().render("unknown", {})
        with self.assertRaises(TypeError):
            MarkdownReportRenderer().render("repository_inventory", {})


class FamilyReportTests(unittest.TestCase):
    def test_build_selection_markdown_and_json(self) -> None:
        data = BuildSelectionReportData(
            entries=(
                BuildSelectionEntry(
                    configuration="debug",
                    selected=("src/main.c",),
                    excluded=("orphan.c",),
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("build_selection", data)
        payload = json.loads(JSONReportRenderer().render("build_selection", data))

        self.assertIn("## debug", markdown)
        self.assertIn("`src/main.c`", markdown)
        self.assertIn("`orphan.c`", markdown)
        self.assertEqual("debug", payload["entries"][0]["configuration"])

    def test_compilation_units_markdown_and_json(self) -> None:
        data = CompilationUnitsReportData(
            entries=(
                CompilationUnitEntry(
                    unit_id="unit-1",
                    configuration="debug",
                    source_path="src/main.c",
                    compiler="gcc",
                    fingerprint="fp-1",
                    define_count=2,
                    include_path_count=1,
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("compilation_units", data)
        payload = json.loads(JSONReportRenderer().render("compilation_units", data))

        self.assertIn("Units recorded: 1", markdown)
        self.assertIn("src/main.c", markdown)
        self.assertEqual(2, payload["entries"][0]["define_count"])

    def test_function_index_markdown_and_json(self) -> None:
        data = FunctionIndexReportData(
            entries=(
                FunctionIndexEntry(
                    name="main",
                    relative_path="src/main.c",
                    line=3,
                    is_definition=True,
                    linkage="external",
                ),
                FunctionIndexEntry(
                    name="helper",
                    relative_path="src/util.h",
                    line=2,
                    is_definition=False,
                    linkage="external",
                ),
            ),
            definition_count=1,
            declaration_count=1,
        )
        markdown = MarkdownReportRenderer().render("function_index", data)
        payload = json.loads(JSONReportRenderer().render("function_index", data))

        self.assertIn("Definitions: 1", markdown)
        self.assertIn("src/main.c:3", markdown)
        self.assertEqual(2, len(payload["entries"]))

    def test_call_graph_markdown_and_json(self) -> None:
        data = CallGraphReportData(
            edges=(
                CallGraphEdge(
                    caller="main",
                    caller_path="src/main.c",
                    call_site_line=8,
                    callee="helper",
                    callee_path="src/util.c",
                    callee_line=1,
                    resolution="confirmed_direct",
                ),
                CallGraphEdge(
                    caller="main",
                    caller_path="src/main.c",
                    call_site_line=9,
                    callee="callback",
                    callee_path=None,
                    callee_line=None,
                    resolution="unresolved",
                ),
            ),
            unresolved_count=1,
        )
        markdown = MarkdownReportRenderer().render("call_graph", data)
        payload = json.loads(JSONReportRenderer().render("call_graph", data))

        self.assertIn("Direct-call edges: 2", markdown)
        self.assertIn("Unresolved edges: 1", markdown)
        self.assertIn("helper", markdown)
        self.assertEqual("unresolved", payload["edges"][1]["resolution"])

    def test_include_index_markdown_and_json(self) -> None:
        data = IncludeIndexReportData(
            entries=(
                IncludeIndexEntry(
                    including_path="src/main.c",
                    line=1,
                    included_spelling="project.h",
                    resolved_path="include/project.h",
                ),
                IncludeIndexEntry(
                    including_path="src/main.c",
                    line=2,
                    included_spelling="generated.h",
                    resolved_path=None,
                ),
            ),
            unresolved_count=1,
        )
        markdown = MarkdownReportRenderer().render("include_index", data)
        payload = json.loads(JSONReportRenderer().render("include_index", data))

        self.assertIn("include/project.h", markdown)
        self.assertIn("unresolved", markdown)
        self.assertEqual("generated.h", payload["entries"][1]["included_spelling"])

    def test_diagnostics_and_capability_indexes(self) -> None:
        diagnostics = DiagnosticsReportData(
            entries=(
                Diagnostic(
                    code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
                    severity=DiagnosticSeverity.ERROR,
                    message="Repository root is unavailable.",
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("diagnostics_index", diagnostics)
        payload = json.loads(JSONReportRenderer().render("diagnostics_index", diagnostics))
        self.assertIn("Diagnostics recorded: 1", markdown)
        self.assertIn("CI-REPO-001", markdown)
        self.assertEqual("CI-REPO-001", payload["entries"][0]["code"])

        capabilities = CapabilityIndexReportData(
            entries=(
                AnalysisCapability(
                    name="make",
                    status=CapabilityStatus.AVAILABLE,
                    reason="GNU Make found on PATH",
                    evidence=("/usr/bin/make",),
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("capability_index", capabilities)
        payload = json.loads(JSONReportRenderer().render("capability_index", capabilities))
        self.assertIn("**make** — available", markdown)
        self.assertEqual("make", payload["entries"][0]["name"])


if __name__ == "__main__":
    unittest.main()
