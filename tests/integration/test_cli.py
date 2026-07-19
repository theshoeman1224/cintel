import contextlib
import io
import json
import shutil
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

    def test_scan_persists_inventory_and_generates_reports(self) -> None:
        fixture = (
            Path(__file__).parents[1] / "fixtures" / "repositories" / "basic"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "basic"
            shutil.copytree(fixture, root)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(["init", str(root)]))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                first_code = main(["--repository", str(root), "scan"])
            self.assertEqual(0, first_code)
            self.assertIn("Relevant files: 4", output.getvalue())
            self.assertTrue((root / ".code-intelligence" / "repository.md").is_file())
            report_path = root / ".code-intelligence" / "reports" / "repository.json"
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(4, payload["metrics"]["files_recorded"])

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                second_code = main(["--repository", str(root), "scan"])
            self.assertEqual(0, second_code)
            self.assertIn("0 computed, 4 reused", output.getvalue())
