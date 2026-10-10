import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.cli.main import main
from cintel.utilities.paths import stable_repository_id

SAMPLES = (
    Path(__file__).parents[1]
    / "fixtures"
    / "complex_c_project"
    / "expected"
    / "sample_inputs"
)


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
            self.assertIn("Repository root is not scannable", stderr)

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
            self.assertIn("No source analysis found yet", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_symbols_before_analyze_exits_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run("--repository", str(root), "symbols")
            self.assertEqual(1, code)
            self.assertIn("No symbols found.", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_context_before_analyze_exits_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run(
                "--repository", str(root), "context", "function", "no_such_function"
            )
            self.assertEqual(1, code)
            self.assertIn("No function named `no_such_function`", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_build_units_before_discovery_exits_no_match_with_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run("--repository", str(root), "build", "units")
            self.assertEqual(1, code)
            self.assertIn("No compilation units found.", stdout)
            self.assertIn("cintel build discover", stdout)

    def test_analyze_on_missing_repository_exits_failure_without_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "not-present"
            code, _, stderr = _run("--repository", str(missing), "analyze")
            self.assertEqual(2, code)
            self.assertIn("not scannable", stderr)
            self.assertFalse((missing / ".code-intelligence").exists())

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "permission checks do not apply to root",
    )
    def test_scan_flags_unwritable_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            locked = Path(directory) / "locked"
            locked.mkdir()
            os.chmod(locked, 0o555)
            try:
                code, _, stderr = _run(
                    "--repository",
                    str(root),
                    "--output-directory",
                    str(locked / "workspace"),
                    "scan",
                )
            finally:
                os.chmod(locked, 0o755)
            self.assertEqual(2, code)
            self.assertIn("Unable to initialize", stderr)

    def test_json_errors_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / ".code-intelligence"
            workspace.mkdir()
            (workspace / "index.sqlite").write_bytes(b"this is not a database")
            code, stdout, _ = _run("--json", "--repository", str(root), "scan")
            self.assertEqual(2, code)
            payload = json.loads(stdout)
            self.assertEqual("StorageError", payload["error"]["type"])
            self.assertIn("Unable to initialize", payload["error"]["message"])

    def test_callers_unknown_function_reports_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, stdout, _ = _run(
                "--repository", str(root), "callers", "no_such_function"
            )
            self.assertEqual(1, code)
            self.assertIn("No function named `no_such_function`", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_setup_and_instructions_reject_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "input.txt"
            sample.write_text("evidence", encoding="utf-8")
            for command in ("setup", "instructions"):
                code, _, stderr = _run(
                    "--repository",
                    str(root),
                    "--input-file",
                    str(sample),
                    command,
                )
                self.assertEqual(2, code, command)
                self.assertIn("run cintel resume", stderr)

    def test_build_discover_honors_input_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, _, _ = _run(
                "--repository",
                str(root),
                "--input-file",
                str(SAMPLES / "macros.txt"),
                "--input-type",
                "macro_listing",
                "build",
                "discover",
            )
            self.assertEqual(2, code)
            storage = SQLiteAnalysisStorage(
                root / ".code-intelligence" / "index.sqlite"
            )
            storage.initialize()
            try:
                artifacts = storage.list_input_artifacts(
                    stable_repository_id(root)
                )
            finally:
                storage.close()
            self.assertEqual(
                ("macro_listing",),
                tuple(item.artifact_type.value for item in artifacts),
            )

    def test_init_falls_back_to_repository_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            code, _, _ = _run("--repository", str(root), "init")
            self.assertEqual(0, code)
            self.assertTrue(
                (root / ".code-intelligence" / "config.toml").is_file()
            )

    def test_output_directory_overrides_conventional_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            self.assertEqual(0, _run("init", str(root))[0])
            alternate = Path(directory) / "alternate"
            code, _, _ = _run(
                "--repository",
                str(root),
                "--output-directory",
                str(alternate),
                "scan",
            )
            self.assertEqual(0, code)
            self.assertTrue((alternate / "index.sqlite").is_file())

    def test_build_discover_prints_make_warning_in_non_tty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, stderr = _run("--repository", str(root), "build", "discover")
            self.assertIn("Make evaluation command:", stderr)
            self.assertIn("may evaluate", stderr)


if __name__ == "__main__":
    unittest.main()
