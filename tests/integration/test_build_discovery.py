import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.artifacts import FileSystemArtifactWriter
from cintel.adapters.build import MakeBuildDiscovery
from cintel.adapters.compiler import GCCCompilerCommandParser
from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application import BuildDiscoveryService, RepositoryScanService
from cintel.cli.main import main
from cintel.configuration.loader import default_config
from cintel.domain.models import CommandRequest, CommandResult


class CountingRunner:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    def run(self, request: CommandRequest) -> CommandResult:
        self.calls += 1
        return CommandResult(
            standard_output=self.output,
            standard_error="",
            exit_code=0,
            duration_seconds=0.1,
            executed_command=request.arguments,
            effective_working_directory=request.working_directory,
        )


class BuildDiscoveryIntegrationTests(unittest.TestCase):
    def test_persists_queries_and_reuses_cached_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text(
                "all:\n\tgcc -Iinclude -DDEBUG -c main.c -o main.o\n",
                encoding="utf-8",
            )
            (root / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
            (root / "not_selected.c").write_text("int unused;\n", encoding="utf-8")
            (root / "include").mkdir()
            config = default_config(root)
            scanner = RepositoryScanService(
                FileSystemRepositoryDiscovery(),
                MarkdownReportRenderer(),
                JSONReportRenderer(),
                FileSystemArtifactWriter(),
                SQLiteAnalysisStorage,
            )
            runner = CountingRunner(
                "API_TOKEN=supersecret gcc -Iinclude -DDEBUG -c main.c -o main.o\n"
            )
            service = BuildDiscoveryService(
                MakeBuildDiscovery(runner, GCCCompilerCommandParser()),
                SQLiteAnalysisStorage,
                scanner,
            )
            build_config = service.create_configuration(
                config,
                makefile=Path("Makefile"),
                working_directory=None,
                target="all",
                make_variables=(),
                environment_overrides=(("API_TOKEN", "supersecret"),),
                name="debug",
                respect_make_timestamps=False,
            )

            first = service.discover(config, build_config)
            second = service.discover(config, build_config)

            self.assertFalse(first.from_cache)
            self.assertTrue(second.from_cache)
            self.assertEqual(1, runner.calls)
            self.assertEqual((str(root / "main.c"),), first.selected_source_files)
            self.assertEqual(
                (str(root / "not_selected.c"),), first.excluded_source_files
            )
            self.assertEqual(1, len(service.list_units(config, "debug")))
            self.assertEqual(1, len(service.show_source(config, "main.c", "debug")))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(
                    [
                        "--repository",
                        str(root),
                        "--build-config",
                        "debug",
                        "build",
                        "units",
                    ]
                )
            self.assertEqual(0, code)
            self.assertIn("main.c", output.getvalue())

            service.discover(config, build_config, force=True)
            self.assertEqual(2, runner.calls)
            connection = sqlite3.connect(config.database_path)
            persisted = "\n".join(
                row[0]
                for table, column in (
                    ("build_configurations", "payload"),
                    ("build_discovery_runs", "payload"),
                    ("compiler_invocations", "payload"),
                    ("build_commands", "raw_content"),
                    ("build_commands", "payload"),
                )
                for row in connection.execute(f"SELECT {column} FROM {table}")
            )
            connection.close()
            self.assertNotIn("supersecret", persisted)
            self.assertIn("***REDACTED***", persisted)

    def test_same_source_can_belong_to_two_build_configurations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "shared.c").write_text("int shared;\n", encoding="utf-8")
            config = default_config(root)
            scanner = RepositoryScanService(
                FileSystemRepositoryDiscovery(),
                MarkdownReportRenderer(),
                JSONReportRenderer(),
                FileSystemArtifactWriter(),
                SQLiteAnalysisStorage,
            )
            runner = CountingRunner("gcc -c shared.c -o shared.o\n")
            service = BuildDiscoveryService(
                MakeBuildDiscovery(runner, GCCCompilerCommandParser()),
                SQLiteAnalysisStorage,
                scanner,
            )
            debug = service.create_configuration(
                config,
                makefile=Path("Makefile"),
                working_directory=None,
                target="all",
                make_variables=(("MODE", "debug"),),
                environment_overrides=(),
                name="debug",
                respect_make_timestamps=False,
            )
            release = service.create_configuration(
                config,
                makefile=Path("Makefile"),
                working_directory=None,
                target="all",
                make_variables=(("MODE", "release"),),
                environment_overrides=(),
                name="release",
                respect_make_timestamps=False,
            )

            service.discover(config, debug)
            service.discover(config, release)
            units = service.list_units(config)

            self.assertEqual(2, len(units))
            self.assertEqual(2, len({item.id for item in units}))
            self.assertEqual(
                {"debug", "release"},
                {
                    name
                    for name in ("debug", "release")
                    if service.list_units(config, name)
                },
            )
