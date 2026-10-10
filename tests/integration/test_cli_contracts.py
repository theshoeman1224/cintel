import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cintel.cli.main import main


def _run(*arguments: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(arguments))
    return code, stdout.getvalue(), stderr.getvalue()


class CLIContractTests(unittest.TestCase):
    def test_scan_on_missing_repository_exits_failure_without_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-present"
            code, stdout, _ = _run("--repository", str(missing), "scan")
            self.assertEqual(2, code)
            self.assertIn("CI-REPO-001", stdout)
            self.assertFalse((missing / ".code-intelligence").exists())

    def test_doctor_on_missing_repository_exits_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-present"
            code, stdout, _ = _run("--repository", str(missing), "doctor")
            self.assertEqual(2, code)
            self.assertIn("CI-REPO-001", stdout)

    def test_report_on_missing_repository_exits_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-present"
            code, _, stderr = _run("--repository", str(missing), "report")
            self.assertEqual(2, code)
            self.assertIn("requires a scannable repository root", stderr)

    def test_malformed_config_exits_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text("not = [valid toml", encoding="utf-8")
            code, _, stderr = _run("--config", str(config), "scan")
            self.assertEqual(2, code)
            self.assertTrue(stderr.startswith("cintel:"))
            self.assertIn("Invalid TOML", stderr)

    def test_corrupt_database_exits_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / ".code-intelligence"
            workspace.mkdir()
            (workspace / "index.sqlite").write_bytes(b"this is not a database")
            code, _, stderr = _run("--repository", str(root), "scan")
            self.assertEqual(2, code)
            self.assertIn("Unable to initialize", stderr)

    def test_newer_database_schema_exits_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / ".code-intelligence"
            workspace.mkdir()
            connection = sqlite3.connect(workspace / "index.sqlite")
            connection.execute(
                "CREATE TABLE schema_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO schema_metadata VALUES ('schema_version', '999')"
            )
            connection.commit()
            connection.close()
            code, _, stderr = _run("--repository", str(root), "scan")
            self.assertEqual(2, code)
            self.assertIn("newer than supported", stderr)

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "permission checks do not apply to root",
    )
    def test_doctor_flags_unwritable_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            locked = Path(directory) / "locked"
            locked.mkdir()
            os.chmod(locked, 0o555)
            try:
                code, stdout, _ = _run(
                    "--repository",
                    str(root),
                    "--output-directory",
                    str(locked / "workspace"),
                    "doctor",
                )
            finally:
                os.chmod(locked, 0o755)
            self.assertEqual(2, code)
            self.assertIn("Output writable: no", stdout)
            self.assertIn("Choose a writable --output-directory.", stdout)

    def test_report_before_analyze_generates_empty_report_families(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run("--repository", str(root), "report")
            self.assertEqual(0, code)
            self.assertIn("Reports generated:", stdout)

    def test_symbols_before_analyze_exits_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run("--repository", str(root), "symbols")
            self.assertEqual(1, code)
            self.assertIn("No symbols found.", stdout)

    def test_context_before_analyze_exits_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, _, _ = _run(
                "--repository", str(root), "context", "function", "no_such_function"
            )
            # The ambiguity message is misleading today and changes in Phase 2.
            self.assertEqual(1, code)

    def test_build_units_before_discovery_reports_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run("--repository", str(root), "build", "units")
            # Phase 2 changes this empty result to exit 1; see docs/IMPROVEMENT_PLAN.md.
            self.assertEqual(0, code)
            self.assertIn("No compilation units found.", stdout)


if __name__ == "__main__":
    unittest.main()
