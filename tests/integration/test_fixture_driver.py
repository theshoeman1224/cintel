import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DRIVER_SCRIPT = PROJECT_ROOT / "scripts" / "fixtures.py"
BASIC_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "repositories" / "basic"


def load_driver():
    spec = importlib.util.spec_from_file_location("fixtures_driver", DRIVER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fixtures_driver"] = module
    spec.loader.exec_module(module)
    return module


driver = load_driver()


class FixtureDriverDiscoveryTests(unittest.TestCase):
    def test_discovers_fixture_modules_and_data_only_directories(self) -> None:
        fixtures = {fixture.name: fixture for fixture in driver.discover_fixtures()}
        self.assertIn("complex_c_project", fixtures)
        self.assertIn("repositories/basic", fixtures)
        self.assertIn("make", fixtures)
        self.assertEqual([], fixtures["make"].available_operations())
        self.assertEqual(
            ["setup", "verify", "clean", "run"],
            fixtures["repositories/basic"].available_operations(),
        )
        self.assertEqual(
            ("make", "gcc", "python3"),
            fixtures["complex_c_project"].requires,
        )

    def test_list_command_reports_fixtures(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = driver.main(["list"])
        self.assertEqual(0, code)
        self.assertIn("complex_c_project", buffer.getvalue())
        self.assertIn("repositories/basic", buffer.getvalue())

    def test_unknown_fixture_name_is_rejected(self) -> None:
        with self.assertRaises(driver.FixtureError):
            driver.select_fixtures(driver.discover_fixtures(), "does-not-exist")


class FixtureDriverOperationTests(unittest.TestCase):
    def make_context(self, fixture_root: Path) -> driver.FixtureContext:
        return driver.FixtureContext(
            repo_root=PROJECT_ROOT,
            fixture_root=fixture_root,
            python=driver.resolve_python(None),
        )

    def test_clean_removes_stray_generated_state_from_a_copy(self) -> None:
        basic = next(
            fixture
            for fixture in driver.discover_fixtures()
            if fixture.name == "repositories/basic"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "basic"
            shutil.copytree(BASIC_FIXTURE, root)
            stray = root / ".code-intelligence"
            stray.mkdir()
            (stray / "marker.txt").write_text("stray", encoding="utf-8")

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                basic.execute("clean", self.make_context(root))
            self.assertFalse(stray.exists())
            self.assertIn("removed stray .code-intelligence", buffer.getvalue())

    def test_verify_reports_missing_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "basic"
            shutil.copytree(BASIC_FIXTURE, root)
            (root / "orphan.c").unlink()
            basic = next(
                fixture
                for fixture in driver.discover_fixtures()
                if fixture.name == "repositories/basic"
            )
            with self.assertRaises(RuntimeError) as raised:
                basic.execute("verify", self.make_context(root))
            self.assertIn("orphan.c", str(raised.exception))

    def test_run_executes_the_basic_lifecycle_without_external_tools(self) -> None:
        basic = next(
            fixture
            for fixture in driver.discover_fixtures()
            if fixture.name == "repositories/basic"
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            basic.execute("run", self.make_context(BASIC_FIXTURE))
        output = buffer.getvalue()
        self.assertIn("run: incremental scan reuses results", output)


if __name__ == "__main__":
    unittest.main()
