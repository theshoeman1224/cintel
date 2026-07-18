import unittest

from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity


class DiagnosticTests(unittest.TestCase):
    def test_accepts_stable_code(self) -> None:
        diagnostic = Diagnostic(
            code="CI-REPO-001",
            severity=DiagnosticSeverity.ERROR,
            message="Repository unavailable",
        )
        self.assertEqual("CI-REPO-001", diagnostic.code)

    def test_rejects_unstable_code(self) -> None:
        with self.assertRaises(ValueError):
            Diagnostic(
                code="repository-error",
                severity=DiagnosticSeverity.ERROR,
                message="Repository unavailable",
            )

