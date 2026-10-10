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
    CallGraphEdge,
    CallGraphReportData,
    CapabilityIndexReportData,
    CapabilityStatus,
    CompilationUnitEntry,
    CompilationUnitsReportData,
    DiagnosticsReportData,
    FunctionIndexEntry,
    FunctionIndexReportData,
    GlobalUsageIndexEntry,
    GlobalUsageReportData,
    IncludeIndexEntry,
    IncludeIndexReportData,
    RepositoryReportData,
    SymbolIndexEntry,
    SymbolIndexReportData,
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
        self.assertIn("## Unresolved includes", markdown)
        self.assertIn("### `generated.h` (1 directives)", markdown)
        self.assertLess(
            markdown.index("## Unresolved includes"),
            markdown.index("## Resolved includes"),
        )
        self.assertIn("- `src/main.c:2`", markdown)
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

    def test_every_markdown_family_explains_its_meaning(self) -> None:
        rendered = []
        with tempfile.TemporaryDirectory() as directory:
            markdown = MarkdownReportRenderer().render(
                "repository_inventory",
                _report_data(_scan(Path(directory), "repo")),
            )
        rendered.append(("repository_inventory", markdown))
        for name, data in (
            ("build_selection", BuildSelectionReportData(entries=())),
            (
                "compilation_units",
                CompilationUnitsReportData(
                    entries=(
                        CompilationUnitEntry(
                            unit_id="unit-1",
                            configuration="debug",
                            source_path="src/main.c",
                            compiler="gcc",
                            fingerprint="fp-1",
                            define_count=0,
                            include_path_count=0,
                        ),
                    )
                ),
            ),
            (
                "function_index",
                FunctionIndexReportData(
                    entries=(
                        FunctionIndexEntry(
                            name="main",
                            relative_path="src/main.c",
                            line=1,
                            is_definition=True,
                            linkage="external",
                        ),
                    ),
                    definition_count=1,
                    declaration_count=0,
                ),
            ),
            (
                "call_graph",
                CallGraphReportData(
                    edges=(
                        CallGraphEdge(
                            caller="main",
                            caller_path="src/main.c",
                            call_site_line=1,
                            callee="helper",
                            callee_path=None,
                            callee_line=None,
                            resolution="unresolved",
                        ),
                    ),
                    unresolved_count=1,
                ),
            ),
            (
                "include_index",
                IncludeIndexReportData(
                    entries=(
                        IncludeIndexEntry(
                            including_path="src/main.c",
                            line=1,
                            included_spelling="stdlib.h",
                            resolved_path=None,
                        ),
                    ),
                    unresolved_count=1,
                ),
            ),
            ("symbol_index", SymbolIndexReportData(entries=())),
            ("global_usage", GlobalUsageReportData(entries=())),
            (
                "diagnostics_index",
                DiagnosticsReportData(
                    entries=(
                        Diagnostic(
                            code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
                            severity=DiagnosticSeverity.INFO,
                            message="informational",
                        ),
                    )
                ),
            ),
            (
                "capability_index",
                CapabilityIndexReportData(
                    entries=(
                        AnalysisCapability(
                            name="example",
                            status=CapabilityStatus.AVAILABLE,
                            reason="reason",
                        ),
                    )
                ),
            ),
        ):
            rendered.append(
                (name, MarkdownReportRenderer().render(name, data))
            )

        for name, markdown in rendered:
            self.assertIn("## What this report means", markdown, name)
            self.assertIn("## Value meanings", markdown, name)


class GroupedLayoutTests(unittest.TestCase):
    """Markdown families group rows so one entity reads at a time.

    The JSON families keep their flat record shape (the fixture
    validator consumes it); grouping is a Markdown presentation rule.
    """

    def test_global_usage_groups_by_variable(self) -> None:
        data = GlobalUsageReportData(
            entries=(
                GlobalUsageIndexEntry(
                    function="telemetry_publish",
                    function_path="src/telemetry/telemetry.c",
                    variable="s_publish_count",
                    variable_path=None,
                ),
                GlobalUsageIndexEntry(
                    function="router_dispatch",
                    function_path="src/routing/router.c",
                    variable="s_handler_count",
                    variable_path="include/cintel_fixture/router.h",
                ),
                GlobalUsageIndexEntry(
                    function="telemetry_initialize",
                    function_path="src/telemetry/telemetry.c",
                    variable="s_publish_count",
                    variable_path=None,
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("global_usage", data)

        self.assertLess(
            markdown.index("### `s_handler_count`"),
            markdown.index("### `s_publish_count`"),
        )
        self.assertIn(
            "- Seen at: `include/cintel_fixture/router.h`", markdown
        )
        publish_section = markdown.split("### `s_publish_count`", 1)[1]
        self.assertIn("- Seen at: not parsed", publish_section)
        self.assertIn(
            "- `telemetry_initialize` (`src/telemetry/telemetry.c`)",
            publish_section,
        )
        self.assertIn(
            "- `telemetry_publish` (`src/telemetry/telemetry.c`)",
            publish_section,
        )
        self.assertNotIn("router_dispatch", publish_section)

    def test_call_graph_groups_calles_under_caller(self) -> None:
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
                CallGraphEdge(
                    caller="runner",
                    caller_path="src/main.c",
                    call_site_line=2,
                    callee="callback",
                    callee_path=None,
                    callee_line=None,
                    resolution="unresolved",
                ),
            ),
            unresolved_count=2,
        )
        markdown = MarkdownReportRenderer().render("call_graph", data)

        self.assertLess(
            markdown.index("## Calls by caller"),
            markdown.index("## Unresolved calls"),
        )
        main_section = (
            markdown.split("### main (`src/main.c`)", 1)[1]
            .split("## Unresolved calls", 1)[0]
        )
        self.assertIn("- `helper` (`src/util.c:1`) — call site 8", main_section)
        self.assertNotIn("`callback`", main_section)
        self.assertIn("### `callback` (2 call sites)", markdown)
        callback_section = markdown.split("### `callback` (2 call sites)")[1]
        self.assertIn("- `main` (`src/main.c`:9)", callback_section)
        self.assertIn("- `runner` (`src/main.c`:2)", callback_section)

    def test_symbol_index_alphabetizes_within_kind(self) -> None:
        data = SymbolIndexReportData(
            entries=(
                SymbolIndexEntry(
                    name="zebra",
                    kind="variable",
                    relative_path="src/a.c",
                    line=1,
                    is_definition=True,
                    linkage="internal",
                ),
                SymbolIndexEntry(
                    name="alpha",
                    kind="variable",
                    relative_path="src/b.c",
                    line=9,
                    is_definition=False,
                    linkage="external",
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("symbol_index", data)

        self.assertIn("## Variables (2)", markdown)
        self.assertLess(
            markdown.index("| alpha | declaration | `src/b.c:9` |"),
            markdown.index("| zebra | definition | `src/a.c:1` |"),
        )

    def test_function_index_heads_one_section_per_file(self) -> None:
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

        self.assertLess(
            markdown.index("## `src/main.c`"),
            markdown.index("## `src/util.h`"),
        )
        self.assertIn(
            "- main — definition, external, `src/main.c:3`", markdown
        )
        self.assertIn(
            "- helper — declaration, external, `src/util.h:2`", markdown
        )

    def test_repository_inventory_groups_by_top_level_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "main.c").write_text(
                "int main(void) { return 0; }\n", encoding="utf-8"
            )
            (root / "src" / "app.c").write_text(
                "int app(void) { return 1; }\n", encoding="utf-8"
            )
            (root / "tests" / "app_test.c").write_text(
                "int app_test(void);\n", encoding="utf-8"
            )
            scan = FileSystemRepositoryDiscovery().discover(
                str(root), "repository-1", ()
            )
            markdown = MarkdownReportRenderer().render(
                "repository_inventory", _report_data(scan)
            )

            self.assertIn("## Files by top-level directory", markdown)
            self.assertIn("- `(root)`: 1 *(calculated metric)*", markdown)
            self.assertIn("- `src`: 1 *(calculated metric)*", markdown)
            self.assertIn("- `tests`: 1 *(calculated metric)*", markdown)
            for item in scan.files:
                self.assertIn(item.content_sha256[:12], markdown)
                self.assertNotIn(item.content_sha256, markdown)

    def test_diagnostics_group_by_code_with_errors_first(self) -> None:
        data = DiagnosticsReportData(
            entries=(
                Diagnostic(
                    code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
                    severity=DiagnosticSeverity.WARNING,
                    message="second",
                ),
                Diagnostic(
                    code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
                    severity=DiagnosticSeverity.ERROR,
                    message="first",
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("diagnostics_index", data)

        self.assertIn("## CI-REPO-001 (2)", markdown)
        self.assertLess(
            markdown.index("- *(error)* first"),
            markdown.index("- *(warning)* second"),
        )

    def test_capability_index_lists_unavailable_before_available(
        self,
    ) -> None:
        data = CapabilityIndexReportData(
            entries=(
                AnalysisCapability(
                    name="alpha",
                    status=CapabilityStatus.AVAILABLE,
                    reason="fine",
                ),
                AnalysisCapability(
                    name="zebra",
                    status=CapabilityStatus.UNAVAILABLE,
                    reason="missing",
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("capability_index", data)

        self.assertLess(
            markdown.index("**zebra** — unavailable"),
            markdown.index("**alpha** — available"),
        )

    def test_build_selection_classifies_against_other_configurations(
        self,
    ) -> None:
        data = BuildSelectionReportData(
            entries=(
                BuildSelectionEntry(
                    configuration="debug",
                    selected=("src/main.c", "src/core.c"),
                    excluded=("orphan.c", "extra.c"),
                ),
                BuildSelectionEntry(
                    configuration="release",
                    selected=("src/main.c", "extra.c"),
                    excluded=("src/core.c", "orphan.c"),
                ),
            )
        )
        markdown = MarkdownReportRenderer().render("build_selection", data)

        debug_section = markdown.split("## debug", 1)[1].split(
            "## release", 1
        )[0]
        self.assertIn(
            "Only in this configuration: 1; "
            "shared with other configurations: 1",
            debug_section,
        )
        self.assertIn(
            "Excluded here, selected elsewhere: 1; "
            "compiled by no recorded configuration: 1",
            debug_section,
        )

    def test_compilation_units_group_by_configuration(self) -> None:
        def unit(unit_id: str, configuration: str) -> CompilationUnitEntry:
            return CompilationUnitEntry(
                unit_id=unit_id,
                configuration=configuration,
                source_path="src/main.c",
                compiler="gcc",
                fingerprint=f"fp-{unit_id}",
                define_count=0,
                include_path_count=0,
            )

        data = CompilationUnitsReportData(
            entries=(unit("unit-2", "release"), unit("unit-1", "debug"))
        )
        markdown = MarkdownReportRenderer().render("compilation_units", data)

        self.assertIn("## debug (1)", markdown)
        self.assertIn("## release (1)", markdown)
        self.assertLess(
            markdown.index("## debug (1)"),
            markdown.index("## release (1)"),
        )


if __name__ == "__main__":
    unittest.main()
