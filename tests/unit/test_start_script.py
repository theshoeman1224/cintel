import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

START_SCRIPT = Path(__file__).resolve().parents[2] / "start.sh"
BASH = shutil.which("bash") or "bash"


@unittest.skipUnless(shutil.which("bash"), "bash is required for start.sh")
class StartScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        # PATH holds only dirname (used while locating the project), so a
        # broken sourcing guard stops at "no Python found" instead of
        # building a virtualenv. resolve_repository needs builtins only.
        bin_directory = tempfile.TemporaryDirectory()
        self.addCleanup(bin_directory.cleanup)
        dirname = shutil.which("dirname")
        if dirname is not None:
            (Path(bin_directory.name) / "dirname").symlink_to(dirname)
        self.path = bin_directory.name

    def _source_and_run(self, command: str, home: str | None = None):
        environment = {"PATH": self.path, "HOME": home or "/nonexistent"}
        return subprocess.run(
            # The script path goes in $1: start.sh treats "sourced" as
            # BASH_SOURCE differing from $0, so it must not also be $0.
            [BASH, "-c", f'source "$1" && {command}', "bash", str(START_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )

    def test_sourcing_loads_helpers_without_running_setup(self) -> None:
        completed = self._source_and_run("type resolve_repository >/dev/null")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stdout)
        self.assertEqual("", completed.stderr)

    def test_missing_repository_reports_an_error_instead_of_crashing(self) -> None:
        completed = self._source_and_run("resolve_repository /no/such/dir")
        self.assertEqual(1, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("'/no/such/dir' is not a directory", completed.stderr)
        self.assertNotIn("cd:", completed.stderr)

    def test_empty_repository_path_is_rejected(self) -> None:
        completed = self._source_and_run('resolve_repository ""')
        self.assertEqual(1, completed.returncode)
        self.assertIn("is not a directory", completed.stderr)

    def test_existing_repository_resolves_to_an_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "repo").mkdir()
            completed = self._source_and_run(
                'cd "$HOME" && resolve_repository repo && resolve_repository "~/repo"',
                home=directory,
            )
            expected = str((Path(directory) / "repo").resolve())
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual([expected, expected], completed.stdout.split())


if __name__ == "__main__":
    unittest.main()
