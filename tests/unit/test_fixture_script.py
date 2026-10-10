import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fixtures.py"
SCRIPT_SPEC = spec_from_file_location("cintel_fixture_driver", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
assert SCRIPT_SPEC.loader is not None
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
        for character in [";", "&", "|", "`", "$", "<", ">", "(", ")", "{", "}", "[", "]", "!", "*", "?", "~", '"', "'", "\\"]:
            self.assertIn(character, FIXTURES.INTERPRETER_FORBIDDEN_CHARACTERS)


class FixtureExecuteBranchTests(unittest.TestCase):
    """Covers the no-handler branches of Fixture.execute."""

    def _fixture(self, fixture_root: Path, module: ModuleType | None) -> object:
        return FIXTURES.Fixture(
            name="stub", fixture_root=fixture_root, module=module
        )

    def _context(self, fixture_root: Path) -> object:
        return FIXTURES.FixtureContext(
            repo_root=fixture_root,
            fixture_root=fixture_root,
            python=sys.executable,
        )

    def test_unknown_operation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, ModuleType("stub"))
            context = self._context(root)
            with self.assertRaises(FIXTURES.FixtureError) as caught:
                fixture.execute("bogus", context)
            self.assertIn("unknown operation: bogus", str(caught.exception))

    def test_data_only_fixture_rejects_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, None)
            context = self._context(root)
            with self.assertRaises(FIXTURES.FixtureError) as caught:
                fixture.execute("setup", context)
            self.assertIn("data-only", str(caught.exception))

    def test_setup_without_handler_reports_nothing_to_do(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, ModuleType("stub"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                fixture.execute("setup", self._context(root))
            self.assertIn(
                "setup: nothing to do (fixture defines no setup)",
                buffer.getvalue(),
            )

    def test_run_without_handler_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, ModuleType("stub"))
            context = self._context(root)
            with self.assertRaises(FIXTURES.FixtureError) as caught:
                fixture.execute("run", context)
            self.assertIn("does not define a run operation", str(caught.exception))

    def test_verify_without_handler_requires_the_fixture_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent"
            fixture = self._fixture(missing, ModuleType("stub"))
            context = self._context(missing)
            with self.assertRaises(FIXTURES.FixtureError) as caught:
                fixture.execute("verify", context)
            self.assertIn("fixture directory is missing", str(caught.exception))

    def test_verify_without_handler_accepts_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, ModuleType("stub"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                fixture.execute("verify", self._context(root))
            self.assertIn(
                "verify: fixture directory present (fixture defines no verify)",
                buffer.getvalue(),
            )

    def test_clean_without_handler_removes_stray_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stray = root / ".code-intelligence"
            stray.mkdir()
            fixture = self._fixture(root, ModuleType("stub"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                fixture.execute("clean", self._context(root))
            self.assertFalse(stray.exists())
            self.assertIn(
                "clean: removed stray .code-intelligence", buffer.getvalue()
            )

    def test_clean_without_handler_reports_nothing_to_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root, ModuleType("stub"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                fixture.execute("clean", self._context(root))
            self.assertIn("clean: nothing to clean", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
