import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fixtures.py"
SCRIPT_SPEC = spec_from_file_location("cintel_fixture_driver", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
FIXTURES = module_from_spec(SCRIPT_SPEC)
sys.modules["cintel_fixture_driver"] = FIXTURES
SCRIPT_SPEC.loader.exec_module(FIXTURES)


class ResolvePythonTests(unittest.TestCase):
    def test_explicit_existing_interpreter_resolves(self) -> None:
        resolved = FIXTURES.resolve_python(sys.executable)

        self.assertTrue(Path(resolved).is_absolute())
        self.assertEqual(Path(sys.executable).resolve(), Path(resolved).resolve())

    def test_explicit_missing_interpreter_is_rejected(self) -> None:
        with self.assertRaises(FIXTURES.FixtureError) as caught:
            FIXTURES.resolve_python("/nonexistent/python-interpreter")

        self.assertIn("not found or not executable", str(caught.exception))

    def test_explicit_non_executable_interpreter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plain_file = Path(directory) / "not-an-interpreter.txt"
            plain_file.write_text("data", encoding="utf-8")

            with self.assertRaises(FIXTURES.FixtureError):
                FIXTURES.resolve_python(str(plain_file))

    def test_explicit_interpreter_found_on_path_resolves(self) -> None:
        with patch.object(FIXTURES.shutil, "which", return_value="/opt/bin/py") as which:
            resolved = FIXTURES.resolve_python("py")

        which.assert_called_once_with("py")
        self.assertEqual("/opt/bin/py", resolved)


class InterpreterValidationTests(unittest.TestCase):
    def test_ensure_environment_rejects_shell_metacharacters(self) -> None:
        for unsafe in (
            "python -c 'import os'; rm -rf /",
            "/bin/sh -c 'echo pwned' && python",
            "/tmp/x\nrm -rf /",
            "python`id`",
            "python$(id)",
        ):
            with self.subTest(value=unsafe):
                with self.assertRaises(FIXTURES.FixtureError) as caught:
                    FIXTURES.ensure_environment(unsafe)

                self.assertIn("unvalidated interpreter", str(caught.exception))

    def test_ensure_environment_rejects_missing_executable(self) -> None:
        with self.assertRaises(FIXTURES.FixtureError) as caught:
            FIXTURES.ensure_environment("/nonexistent/python-interpreter")

        self.assertIn("unvalidated interpreter", str(caught.exception))

    def test_ensure_environment_invokes_installer_with_validated_interpreter(
        self,
    ) -> None:
        with (
            patch.object(FIXTURES.os, "access", return_value=True),
            patch.object(FIXTURES.subprocess, "run") as run,
            patch("builtins.print"),
        ):
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            FIXTURES.ensure_environment(sys.executable)

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual([sys.executable, str(FIXTURES.INSTALL_SCRIPT)], command)

    def test_cintel_rejects_unvalidated_context_python(self) -> None:
        context = FIXTURES.FixtureContext(
            repo_root=Path("."),
            fixture_root=Path("."),
            python="/nonexistent/python-interpreter",
        )

        with self.assertRaises(FIXTURES.FixtureError) as caught:
            context.cintel(["scan"])

        self.assertIn("unvalidated interpreter", str(caught.exception))

    def test_cintel_runs_validated_context_python(self) -> None:
        context = FIXTURES.FixtureContext(
            repo_root=Path("."),
            fixture_root=Path("."),
            python=sys.executable,
        )

        with patch.object(context, "run") as run:
            context.cintel(["scan"])

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual([sys.executable, "-m", "cintel", "scan"], command)


class ForbiddenCharacterCoverageTests(unittest.TestCase):
    def test_shell_control_characters_are_forbidden(self) -> None:
        for character in "; & | ` $ < > ( ) { } [ ] ! * ? ~ \" ' \\".split():
            self.assertIn(character, FIXTURES.INTERPRETER_FORBIDDEN_CHARACTERS)


if __name__ == "__main__":
    unittest.main()
