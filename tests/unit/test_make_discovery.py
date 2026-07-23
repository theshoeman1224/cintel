import tempfile
import unittest
from pathlib import Path

from cintel.adapters.build import MakeBuildDiscovery, make_dry_run_arguments
from cintel.adapters.compiler import GCCCompilerCommandParser
from cintel.application import parse_assignments
from cintel.domain.errors import ConfigurationError
from cintel.domain.models import BuildConfiguration, CommandRequest, CommandResult


class FakeRunner:
    def __init__(self, output: str, exit_code: int = 0) -> None:
        self.output = output
        self.exit_code = exit_code
        self.requests: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        return CommandResult(
            standard_output=self.output,
            standard_error="" if self.exit_code == 0 else "make failed",
            exit_code=self.exit_code,
            duration_seconds=0.25,
            executed_command=request.arguments,
            effective_working_directory=request.working_directory,
        )


class StaticCompilerMetadata:
    def version(self, executable: str, working_directory: str) -> str | None:
        return f"{executable} version 1.2.3"


def configuration(root: Path, respect_timestamps: bool = False) -> BuildConfiguration:
    return BuildConfiguration(
        id="build-1",
        repository_id="repository-1",
        name="debug",
        repository_root=str(root),
        makefile=str(root / "Makefile"),
        working_directory=str(root),
        target="all",
        make_variables=(("MODE", "debug"),),
        environment_overrides=(("SDK", "/opt/sdk"),),
        respect_make_timestamps=respect_timestamps,
    )


class MakeDiscoveryTests(unittest.TestCase):
    def test_parses_make_and_environment_assignments(self) -> None:
        self.assertEqual(
            (("NAME", "value=with=equals"),),
            parse_assignments(["NAME=value=with=equals"], "--make-var"),
        )
        with self.assertRaises(ConfigurationError):
            parse_assignments(["MISSING_VALUE"], "--env")

    def test_builds_safe_dry_run_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = configuration(Path(directory))
            self.assertEqual(
                (
                    "make",
                    "-n",
                    "-B",
                    "-f",
                    str(Path(directory) / "Makefile"),
                    "all",
                    "MODE=debug",
                ),
                make_dry_run_arguments(config),
            )
            self.assertNotIn(
                "-B",
                make_dry_run_arguments(configuration(Path(directory), True)),
            )

    def test_parses_recursive_directories_cd_wrappers_and_malformed_content(self) -> None:
        fixture = Path(__file__).parents[1] / "fixtures" / "make" / "dry_run_recursive.txt"
        output = fixture.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "sub" / "src").mkdir(parents=True)
            (root / "sub" / "nested").mkdir()
            (root / "sub" / "deeper").mkdir()
            (root / "sub" / "src" / "worker.c").write_text("int worker;\n", encoding="utf-8")
            (root / "sub" / "nested" / "helper.c").write_text("int helper;\n", encoding="utf-8")
            (root / "sub" / "deeper" / "deep.c").write_text("int deep;\n", encoding="utf-8")
            adapter = MakeBuildDiscovery(FakeRunner(output), GCCCompilerCommandParser())

            result = adapter.discover(configuration(root))

            self.assertEqual(4, len(result.compiler_invocations))
            self.assertEqual(3, len(result.compilation_units))
            self.assertEqual(
                {"recursive_make", "directory_change", "compiler", "other", "unparsed"},
                {item.classification for item in result.commands},
            )
            helper = next(
                item
                for item in result.compiler_invocations
                if item.source and item.source.original == "helper.c"
            )
            self.assertEqual(str(root / "sub" / "nested"), helper.working_directory)
            deep = next(
                item
                for item in result.compiler_invocations
                if item.source and item.source.original == "deep.c"
            )
            self.assertEqual(str(root / "sub" / "deeper"), deep.working_directory)
            self.assertIn("CI-BUILD-003", {item.code for item in result.diagnostics})
            self.assertIn("CI-BUILD-005", {item.code for item in result.diagnostics})
            self.assertEqual(output, result.raw_output)

    def test_nonzero_make_result_degrades_but_preserves_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "main.c").write_text("int main;\n", encoding="utf-8")
            adapter = MakeBuildDiscovery(
                FakeRunner("gcc -c main.c -o main.o\n", exit_code=2),
                GCCCompilerCommandParser(),
            )
            result = adapter.discover(configuration(root))
            self.assertEqual(1, len(result.compilation_units))
            self.assertIn("CI-BUILD-002", {item.code for item in result.diagnostics})

    def test_build_fingerprint_includes_available_compiler_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "main.c").write_text("int main;\n", encoding="utf-8")
            result = MakeBuildDiscovery(
                FakeRunner("gcc -c main.c -o main.o\n"),
                GCCCompilerCommandParser(),
                StaticCompilerMetadata(),
            ).discover(configuration(root))
            self.assertEqual(
                (("gcc", "gcc version 1.2.3"),), result.compiler_versions
            )
            self.assertEqual(
                "available", result.capabilities[-1].status.value
            )

    def test_identical_repeated_compile_command_is_preserved_but_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "main.c").write_text("int main;\n", encoding="utf-8")
            command = "gcc -c main.c -o main.o"
            result = MakeBuildDiscovery(
                FakeRunner(f"{command}\n{command}\n"), GCCCompilerCommandParser()
            ).discover(configuration(root))
            self.assertEqual(2, len(result.commands))
            self.assertEqual(1, len(result.compiler_invocations))
            self.assertEqual(1, len(result.compilation_units))

    def test_missing_make_degrades_with_structured_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            result = MakeBuildDiscovery(
                FakeRunner("", exit_code=127), GCCCompilerCommandParser()
            ).discover(configuration(root))
            codes = {item.code for item in result.diagnostics}
            self.assertIn("CI-BUILD-001", codes)
            self.assertIn("CI-COMP-001", codes)
            self.assertEqual("unavailable", result.capabilities[0].status.value)
