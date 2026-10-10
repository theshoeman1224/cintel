import tempfile
import unittest
from pathlib import Path

from cintel.adapters.guidance import StandardInputGuidanceProvider
from cintel.adapters.reports import MarkdownGuidanceRenderer
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import BuildConfiguration, CommandRisk


class GuidanceTests(unittest.TestCase):
    def test_generates_exact_redacted_make_capture_and_resume_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = BuildConfiguration(
                id="build-1",
                repository_id="repository-1",
                name="linux",
                repository_root=str(root),
                makefile=str(root / "Makefile"),
                working_directory=str(root),
                target="linux",
                make_variables=(("MODE", "debug"), ("API_TOKEN", "secret-value")),
            )
            diagnostic = Diagnostic(
                code="CI-INPUT-001",
                severity=DiagnosticSeverity.WARNING,
                message="Build evidence missing",
                missing_capability="compilation_units",
                recoverability=Recoverability.USER_ACTION,
            )
            instructions = StandardInputGuidanceProvider().instructions_for(
                str(root), str(root / ".code-intelligence"), (diagnostic,), configuration
            )
            rendered = MarkdownGuidanceRenderer().render("required_inputs", instructions)

        self.assertEqual(CommandRisk.MAKEFILE_EVALUATION, instructions[0].risk)
        self.assertIn("MODE=debug", instructions[0].arguments)
        self.assertIn("API_TOKEN=<SET_LOCALLY>", instructions[0].arguments)
        self.assertNotIn("secret-value", rendered)
        self.assertIn("make -n -B", rendered)
        self.assertIn("make -n may still execute", rendered)
        self.assertIn("--input-file", instructions[0].resume_command)

    def test_provider_falls_back_to_file_list_when_make_is_not_the_gap(self) -> None:
        diagnostic = Diagnostic(
            code=DiagnosticCode.NO_COMPILER_RECOGNIZED,
            severity=DiagnosticSeverity.WARNING,
            message="No compiler was found.",
            missing_capability="gcc_enrichment",
            recoverability=Recoverability.REDUCED_CAPABILITY,
        )
        with tempfile.TemporaryDirectory() as directory:
            instructions = StandardInputGuidanceProvider().instructions_for(
                directory, str(Path(directory) / ".code-intelligence"), (diagnostic,)
            )
        self.assertEqual(1, len(instructions))
        self.assertEqual(
            "Capture a source-oriented repository file list", instructions[0].title
        )
        self.assertIn("repository-files.txt", instructions[0].expected_output_file)
        self.assertEqual(CommandRisk.READ_ONLY, instructions[0].risk)

    def test_provider_uses_default_names_without_a_build_configuration(self) -> None:
        diagnostic = Diagnostic(
            code=DiagnosticCode.MAKE_DRY_RUN_INCOMPLETE,
            severity=DiagnosticSeverity.INFO,
            message="No Makefile was detected.",
            missing_capability="compilation_units",
            recoverability=Recoverability.REDUCED_CAPABILITY,
        )
        with tempfile.TemporaryDirectory() as directory:
            instructions = StandardInputGuidanceProvider().instructions_for(
                directory, str(Path(directory) / ".code-intelligence"), (diagnostic,)
            )
        self.assertEqual(("make", "-n", "-B", "V=1"), instructions[0].arguments)
        self.assertTrue(
            instructions[0].expected_output_file.endswith("default-make-dry-run.txt")
        )
        self.assertEqual(str(Path(directory).resolve()), instructions[0].working_directory)

    def test_provider_adds_search_instruction_for_missing_source_paths(self) -> None:
        diagnostic = Diagnostic(
            code=DiagnosticCode.MISSING_SOURCE_FILE,
            severity=DiagnosticSeverity.WARNING,
            message="A compiler command references a missing file.",
            related_paths=("src/generated.c",),
        )
        with tempfile.TemporaryDirectory() as directory:
            instructions = StandardInputGuidanceProvider().instructions_for(
                directory, str(Path(directory) / ".code-intelligence"), (diagnostic,)
            )
        self.assertEqual(1, len(instructions))
        self.assertEqual(
            "Locate missing build input generated.c", instructions[0].title
        )
        self.assertEqual(
            ("find", ".", "-name", "generated.c", "-print"), instructions[0].arguments
        )

    def test_renderer_rejects_unsupported_report_names(self) -> None:
        renderer = MarkdownGuidanceRenderer()
        with self.assertRaises(ValueError):
            renderer.render("something_else", ())

    def test_renderer_rejects_non_instruction_items(self) -> None:
        renderer = MarkdownGuidanceRenderer()
        with self.assertRaises(TypeError):
            renderer.render("required_inputs", (object(),))

    def test_renderer_handles_empty_instructions(self) -> None:
        rendered = MarkdownGuidanceRenderer().render("required_inputs", ())
        self.assertIn("No additional inputs are currently required.", rendered)


if __name__ == "__main__":
    unittest.main()
