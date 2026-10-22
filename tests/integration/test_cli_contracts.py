import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            _run("init", str(root))
            code, stdout, _ = _run("--repository", str(root), "symbols")
            self.assertEqual(1, code)
            self.assertIn("No symbols found.", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_context_before_analyze_exits_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _run("init", str(root))
            code, stdout, _ = _run(
                "--repository", str(root), "context", "function", "no_such_function"
            )
            self.assertEqual(1, code)
            self.assertIn("No function named `no_such_function`", stdout)
            self.assertIn("cintel analyze", stdout)

    def test_build_units_before_discovery_exits_no_match_with_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _run("init", str(root))
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
            _run("init", str(root))
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
            # Force a non-TTY stdin: on a terminal the CLI would prompt and
            # the suite would block waiting for an answer.
            with mock.patch("sys.stdin", io.StringIO()):
                _, _, stderr = _run(
                    "--repository", str(root), "build", "discover"
                )
            self.assertIn("Make evaluation command:", stderr)
            self.assertIn("may evaluate", stderr)

    def test_interactive_build_discover_previews_once(self) -> None:
        class _Terminal(io.StringIO):
            def isatty(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch("sys.stdin", _Terminal()),
                mock.patch("builtins.input", return_value="n"),
            ):
                code, _, stderr = _run(
                    "--repository", str(root), "build", "discover"
                )
        self.assertEqual(2, code)
        self.assertEqual(1, stderr.count("Make evaluation command:"))
        self.assertEqual(1, stderr.count("may evaluate"))
        self.assertIn("Build discovery cancelled.", stderr)

    def test_missing_build_configuration_names_the_discovered_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "src").mkdir(parents=True)
            (root / "src" / "main.c").write_text(
                "int main(void) { return 0; }\n", encoding="utf-8"
            )
            (root / "Makefile").write_text("all:\n\tgcc -c src/main.c\n", encoding="utf-8")
            evidence = Path(directory) / "dry-run.txt"
            evidence.write_text("gcc -c src/main.c -o main.o\n", encoding="utf-8")
            base = ["--repository", str(root)]
            _run("init", str(root))
            code, stdout, _ = _run(
                *base, "--build-config", "debug", "--makefile", "Makefile",
                "--non-interactive", "--input-file", str(evidence),
                "build", "discover",
            )
            self.assertEqual(0, code, stdout)

            code, stdout, _ = _run(*base, "build", "units")
            self.assertEqual(1, code)
            self.assertIn("`default`", stdout)
            self.assertIn("Discovered configurations: debug", stdout)

            code, stdout, _ = _run(*base, "build", "show", "src/main.c")
            self.assertEqual(1, code)
            self.assertIn("Discovered configurations: debug", stdout)

            code, stdout, _ = _run(*base, "--json", "analyze")
            self.assertEqual(0, code, stdout)
            summary = json.loads(stdout)
            messages = [item["message"] for item in summary["diagnostics"]]
            self.assertTrue(
                any("`default`" in item and "debug" in item for item in messages),
                messages,
            )

            code, stdout, _ = _run(*base, "--build-config", "debug", "--json", "analyze")
            self.assertEqual(0, code, stdout)
            self.assertEqual([], json.loads(stdout)["diagnostics"])

    def test_read_only_commands_do_not_create_a_workspace(self) -> None:
        commands = {
            ("symbols",): "cintel analyze",
            ("show", "function", "main"): "cintel analyze",
            ("callers", "main"): "cintel analyze",
            ("callees", "main"): "cintel analyze",
            ("context", "function", "main"): "cintel analyze",
            ("build", "units"): "cintel build discover",
            ("build", "show", "main.c"): "cintel build discover",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for arguments, next_step in commands.items():
                code, stdout, _ = _run("--repository", str(root), *arguments)
                self.assertEqual(1, code, arguments)
                self.assertIn("No cintel workspace", stdout, arguments)
                self.assertIn("cintel init", stdout, arguments)
                self.assertIn(next_step, stdout, arguments)
            code, stdout, _ = _run("--repository", str(root), "--json", "symbols")
            self.assertEqual(1, code)
            self.assertEqual(
                "WorkspaceNotFound", json.loads(stdout)["error"]["type"]
            )
            self.assertFalse((root / ".code-intelligence").exists())

    def test_verbose_reports_configuration_source_and_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, stderr = _run("--repository", str(root), "--verbose", "doctor")
            self.assertIn("cintel: configuration: built-in defaults", stderr)
            self.assertRegex(stderr, r"cintel: doctor finished in \d+\.\d+s")

            _run("init", str(root))
            config = root / ".code-intelligence" / "config.toml"
            _, _, stderr = _run("--repository", str(root), "--verbose", "scan")
            self.assertIn(f"cintel: configuration: {config}", stderr)
            self.assertRegex(stderr, r"cintel: scan finished in \d+\.\d+s")

            _, _, stderr = _run("--config", str(config), "--verbose", "build", "units")
            self.assertIn("(from --config)", stderr)
            self.assertRegex(stderr, r"cintel: build units finished in")

            _, _, stderr = _run("--repository", str(root), "scan")
            self.assertNotIn("cintel:", stderr)

    def test_enabled_ai_setting_warns_that_it_has_no_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _run("init", str(root))
            config = root / ".code-intelligence" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "enabled = false", "enabled = true"
                ),
                encoding="utf-8",
            )
            _, _, stderr = _run("--repository", str(root), "scan")
            self.assertIn("[ai] enabled = true has no effect", stderr)
            code, stdout, _ = _run("--repository", str(root), "doctor")
            self.assertIn("CI-CONF-001", stdout)


if __name__ == "__main__":
    unittest.main()
