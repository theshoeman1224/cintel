import tempfile
import unittest
from pathlib import Path

from cintel.adapters.guidance import StandardInputGuidanceProvider
from cintel.adapters.reports import MarkdownGuidanceRenderer
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity, Recoverability
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


if __name__ == "__main__":
    unittest.main()
