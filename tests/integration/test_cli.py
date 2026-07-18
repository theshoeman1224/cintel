import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cintel.cli.main import main


class CLIIntegrationTests(unittest.TestCase):
    def test_init_and_doctor_are_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                init_code = main(["init", str(root)])
            self.assertEqual(0, init_code)
            self.assertIn("Initialized Legacy C Code Intelligence", output.getvalue())

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                doctor_code = main(["--repository", str(root), "doctor"])
            self.assertIn(doctor_code, (0, 2))
            self.assertIn("Legacy C Code Intelligence doctor", output.getvalue())

    def test_init_json_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--json", "init", directory])
            self.assertEqual(0, code)
            payload = json.loads(output.getvalue())
            self.assertEqual(str(Path(directory).resolve()), payload["repository"]["root"])
