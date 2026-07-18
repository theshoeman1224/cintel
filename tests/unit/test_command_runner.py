import sys
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.commands import SubprocessCommandRunner
from cintel.domain.models import (
    CommandRequest,
    CommandRisk,
    OutputDestination,
)


class CommandRunnerTests(unittest.TestCase):
    def test_captures_command_result_and_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = CommandRequest(
                arguments=(
                    sys.executable,
                    "-c",
                    "import os; print(os.environ['CINTEL_TEST_VALUE'])",
                ),
                working_directory=directory,
                environment_overrides=(("CINTEL_TEST_VALUE", "visible"),),
                risk=CommandRisk.READ_ONLY,
            )

            result = SubprocessCommandRunner().run(request)

            self.assertEqual(0, result.exit_code)
            self.assertEqual("visible", result.standard_output.strip())
            self.assertEqual(request.arguments, result.executed_command)
            self.assertEqual(str(Path(directory).resolve()), result.effective_working_directory)
            self.assertGreaterEqual(result.duration_seconds, 0)

    def test_file_destination_writes_captured_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.txt"
            result = SubprocessCommandRunner().run(
                CommandRequest(
                    arguments=(sys.executable, "-c", "print('saved')"),
                    working_directory=directory,
                    output_destination=OutputDestination.FILE,
                    output_file=str(output),
                )
            )
            self.assertEqual(0, result.exit_code)
            self.assertEqual("saved\n", output.read_text(encoding="utf-8"))

    def test_missing_executable_is_captured_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = SubprocessCommandRunner().run(
                CommandRequest(
                    arguments=("/definitely/missing/cintel-command",),
                    working_directory=directory,
                )
            )
            self.assertEqual(127, result.exit_code)
            self.assertTrue(result.standard_error)
