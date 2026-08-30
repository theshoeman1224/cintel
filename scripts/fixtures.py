#!/usr/bin/env python3
"""Drive the test fixtures under tests/fixtures/.

Each fixture directory may provide a ``fixture.py`` exposing any subset of
``setup(ctx)``, ``verify(ctx)``, ``clean(ctx)``, and ``run(ctx)`` plus the
optional constants ``NAME``, ``DESCRIPTION``, and ``REQUIRES``. The driver
discovers those modules automatically, so adding a new fixture requires no
changes to this script. Fixtures without a ``fixture.py`` are data-only.

Operations delegate to the scripts that already exist in the repository
(scripts/install.py, per-fixture tools such as tools/verify_fixture.py and
tools/validate_cintel_results.py, and the documented cintel CLI flow), so the
setup a fixture receives matches what a user of this repository gets.

Usage:
    python scripts/fixtures.py list
    python scripts/fixtures.py (setup|verify|clean|run) (NAME|all)
        [--output-dir DIR] [--no-bootstrap] [--python PYTHON] [-v]
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = PROJECT_ROOT / "tests" / "fixtures"
INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install.py"
OPERATIONS = ("setup", "verify", "clean", "run")
DEFAULT_TIMEOUT = 600


class FixtureError(RuntimeError):
    """Raised when a fixture operation fails."""


@dataclasses.dataclass
class FixtureContext:
    """Services handed to every fixture operation."""

    repo_root: Path
    fixture_root: Path
    python: str
    verbose: bool = False
    output_dir: Path | None = None

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if env:
            environment.update(env)
        if self.verbose:
            print(f"  $ {' '.join(command)}")
        completed = subprocess.run(
            command,
            cwd=str(cwd or self.fixture_root),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=environment,
        )
        if completed.returncode != 0 and check:
            detail = (completed.stdout + completed.stderr).strip()
            raise FixtureError(
                f"command failed ({' '.join(command)}): {detail or 'no output'}"
            )
        return completed

    def cintel(self, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run ``python -m cintel`` with the src layout on PYTHONPATH."""
        environment = {"PYTHONPATH": str(self.repo_root / "src")}
        return self.run(
            [self.python, "-m", "cintel", *arguments],
            cwd=self.repo_root,
            check=check,
            env=environment,
        )

    @contextlib.contextmanager
    def copy_to_tempdir(self, ignore: tuple[str, ...] = (".code-intelligence", "build")):
        """Copy the fixture tree to a fresh temporary workspace."""
        with tempfile.TemporaryDirectory(prefix="cintel-fixture-") as directory:
            destination = Path(directory) / self.fixture_root.name
            shutil.copytree(
                self.fixture_root,
                destination,
                ignore=shutil.ignore_patterns(*ignore),
            )
            yield destination


@dataclasses.dataclass
class Fixture:
    name: str
    fixture_root: Path
    module: ModuleType | None

    @property
    def description(self) -> str:
        return getattr(self.module, "DESCRIPTION", "data-only fixture (no fixture.py)")

    @property
    def requires(self) -> tuple[str, ...]:
        return tuple(getattr(self.module, "REQUIRES", ()))

    def missing_requirements(self) -> list[str]:
        return [tool for tool in self.requires if shutil.which(tool) is None]

    def available_operations(self) -> list[str]:
        if self.module is None:
            return []
        return [op for op in OPERATIONS if callable(getattr(self.module, op, None))]

    def execute(self, operation: str, context: FixtureContext) -> None:
        if operation not in OPERATIONS:
            raise FixtureError(f"unknown operation: {operation}")
        if self.module is None:
            raise FixtureError(f"fixture {self.name} is data-only and defines no operations")
        handler = getattr(self.module, operation, None)
        if not callable(handler):
            if operation == "run":
                raise FixtureError(f"fixture {self.name} does not define a run operation")
            if operation == "setup":
                print("  setup: nothing to do (fixture defines no setup)")
                return
            if operation == "verify":
                if not self.fixture_root.is_dir():
                    raise FixtureError(f"fixture directory is missing: {self.fixture_root}")
                print("  verify: fixture directory present (fixture defines no verify)")
                return
            if operation == "clean":
                stray = self.fixture_root / ".code-intelligence"
                if stray.exists():
                    shutil.rmtree(stray)
                    print("  clean: removed stray .code-intelligence")
                else:
                    print("  clean: nothing to clean")
                return
        handler(context)


def _fixture_for(directory: Path) -> Fixture | None:
    script = directory / "fixture.py"
    name = directory.relative_to(FIXTURES_ROOT).as_posix()
    if script.is_file():
        return Fixture(name=name, fixture_root=directory, module=load_module(script, name))
    if any(path.is_file() for path in directory.iterdir()):
        return Fixture(name=name, fixture_root=directory, module=None)
    return None


def discover_fixtures() -> list[Fixture]:
    fixtures: list[Fixture] = []
    if not FIXTURES_ROOT.is_dir():
        return fixtures
    for entry in sorted(path for path in FIXTURES_ROOT.iterdir() if path.is_dir()):
        fixture = _fixture_for(entry)
        if fixture is not None:
            fixtures.append(fixture)
            continue
        for child in sorted(path for path in entry.iterdir() if path.is_dir()):
            fixture = _fixture_for(child)
            if fixture is not None:
                fixtures.append(fixture)
    return fixtures


def load_module(path: Path, name: str) -> ModuleType | None:
    identifier = "cintel_fixture_" + name.replace("/", "_").replace("-", "_")
    spec = importlib.util.spec_from_file_location(identifier, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[identifier] = module
    spec.loader.exec_module(module)
    return module


def resolve_python(explicit: str | None) -> str:
    if explicit:
        return explicit
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def ensure_environment(python: str) -> None:
    """Bootstrap the environment the same way a user would (start.sh flow)."""
    if not INSTALL_SCRIPT.is_file():
        raise FixtureError(f"installer is missing: {INSTALL_SCRIPT}")
    completed = subprocess.run(
        [python, str(INSTALL_SCRIPT)], text=True, capture_output=True, check=False, timeout=300
    )
    if completed.returncode != 0:
        raise FixtureError(
            f"environment bootstrap failed:\n{(completed.stdout + completed.stderr).strip()}"
        )
    print(f"Environment ready ({python}); cintel install is current.")


def select_fixtures(fixtures: list[Fixture], target: str) -> list[Fixture]:
    if target == "all":
        return fixtures
    for fixture in fixtures:
        if fixture.name == target:
            return [fixture]
    known = ", ".join(fixture.name for fixture in fixtures) or "none discovered"
    raise FixtureError(f"unknown fixture {target!r}; known fixtures: {known}")


def apply_operation(fixtures: list[Fixture], operation: str, options: argparse.Namespace) -> int:
    python = resolve_python(options.python)
    failures: list[str] = []
    for fixture in fixtures:
        print(f"\n=== {operation}: {fixture.name} ===")
        print(f"  {fixture.description}")
        missing = fixture.missing_requirements()
        needs_environment = operation == "run"
        if missing and operation != "clean":
            print(f"  skipped: missing required tools: {', '.join(missing)}")
            continue
        try:
            if needs_environment and not options.no_bootstrap:
                ensure_environment(python)
            context = FixtureContext(
                repo_root=PROJECT_ROOT,
                fixture_root=fixture.fixture_root,
                python=python,
                verbose=options.verbose,
                output_dir=options.output_dir,
            )
            fixture.execute(operation, context)
        except (FixtureError, RuntimeError, subprocess.TimeoutExpired, OSError) as error:
            failures.append(fixture.name)
            print(f"  FAILED: {error}", file=sys.stderr)
    if failures:
        print(f"\n{operation} failed for: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"\n{operation} completed successfully.")
    return 0


def command_list(fixtures: list[Fixture]) -> int:
    print(f"Fixtures under {FIXTURES_ROOT}:")
    for fixture in fixtures:
        requirements = f" (requires: {', '.join(fixture.requires)})" if fixture.requires else ""
        operations = ", ".join(fixture.available_operations()) or "none"
        print(f"\n  {fixture.name}{requirements}")
        print(f"    {fixture.description}")
        print(f"    operations: {operations}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover, set up, verify, clean, and run the test fixtures."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list discovered fixtures and their operations")
    for operation in OPERATIONS:
        sub = subparsers.add_parser(operation, help=f"{operation} a fixture (or 'all')")
        sub.add_argument("target", help="fixture name (see 'list') or 'all'")
        sub.add_argument("--output-dir", type=Path, default=None, help="output directory for run results")
        sub.add_argument("--no-bootstrap", action="store_true", help="skip scripts/install.py bootstrap")
        sub.add_argument("--python", default=None, help="interpreter used for cintel and fixture tools")
        sub.add_argument("-v", "--verbose", action="store_true", help="print commands and captured output")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    fixtures = discover_fixtures()
    if options.command == "list":
        return command_list(fixtures)
    if not fixtures:
        print(f"error: no fixtures discovered under {FIXTURES_ROOT}", file=sys.stderr)
        return 1
    selected = select_fixtures(fixtures, options.target)
    return apply_operation(selected, options.command, options)


if __name__ == "__main__":
    raise SystemExit(main())
