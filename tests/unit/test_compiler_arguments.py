import tempfile
import unittest
from pathlib import Path

from cintel.adapters.compiler import (
    GCCCompilerCommandParser,
    GCCCompilerMetadataProvider,
)
from cintel.domain.models import CommandRequest, CommandResult


class MetadataRunner:
    def __init__(self) -> None:
        self.request: CommandRequest | None = None

    def run(self, request: CommandRequest) -> CommandResult:
        self.request = request
        return CommandResult(
            standard_output="gcc (GCC) 12.2.0\nCopyright\n",
            standard_error="",
            exit_code=0,
            duration_seconds=0.01,
            executed_command=request.arguments,
            effective_working_directory=request.working_directory,
        )


class CompilerArgumentParserTests(unittest.TestCase):
    def test_extracts_required_gcc_arguments_and_preserves_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "build"
            work.mkdir()
            parser = GCCCompilerCommandParser()

            invocations = parser.parse(
                "gcc -I../include -I local -isystem /sdk/include "
                "-DDEBUG -DLEVEL=3 -UOLD -include ../config.h "
                "-std=gnu11 -O2 -g3 -Wall -mcpu=cortex-m4 "
                "-MMD -MF main.d -c ../src/main.c -o main.o --mystery",
                str(work),
                str(root),
                "build-1",
            )

            self.assertIsNotNone(invocations)
            invocation = invocations[0]  # type: ignore[index]
            self.assertEqual("gcc", invocation.compiler_executable)
            self.assertEqual("../src/main.c", invocation.source.original)
            self.assertEqual("src/main.c", invocation.source.repository_relative)
            self.assertEqual("build/main.o", invocation.object_file.repository_relative)
            self.assertEqual(
                ("include", "build/local", None),
                tuple(item.path.repository_relative for item in invocation.arguments.include_paths),
            )
            self.assertTrue(invocation.arguments.include_paths[-1].is_system)
            self.assertEqual(
                (("DEBUG", None), ("LEVEL", "3")),
                tuple((item.name, item.value) for item in invocation.arguments.defines),
            )
            self.assertEqual(("OLD",), invocation.arguments.undefines)
            self.assertEqual("config.h", invocation.arguments.forced_includes[0].repository_relative)
            self.assertEqual("gnu11", invocation.arguments.language_standard)
            self.assertEqual(("-O2",), invocation.arguments.optimization_flags)
            self.assertEqual(("-g3",), invocation.arguments.debug_flags)
            self.assertEqual(("-Wall",), invocation.arguments.warning_flags)
            self.assertEqual(("-mcpu=cortex-m4",), invocation.arguments.architecture_flags)
            self.assertEqual(("-MMD", "-MF", "main.d"), invocation.arguments.dependency_flags)
            self.assertEqual(("-c", "--mystery"), invocation.arguments.unclassified_arguments)

    def test_detects_wrappers_environment_and_cross_compiler(self) -> None:
        parser = GCCCompilerCommandParser()
        result = parser.parse(
            "MODE=debug env CACHE=yes ccache distcc arm-linux-gnueabihf-gcc -c main.c",
            "/repo",
            "/repo",
            "build-1",
        )
        self.assertIsNotNone(result)
        invocation = result[0]  # type: ignore[index]
        self.assertEqual("arm-linux-gnueabihf-gcc", invocation.compiler_executable)
        self.assertEqual(
            ("MODE=debug", "env", "CACHE=yes", "ccache", "distcc"),
            invocation.launchers,
        )

    def test_detects_nice_and_time_wrappers(self) -> None:
        result = GCCCompilerCommandParser().parse(
            "nice -n 5 time -p gcc -c main.c",
            "/repo",
            "/repo",
            "build-1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(("nice", "-n", "5", "time", "-p"), result[0].launchers)  # type: ignore[index]

    def test_returns_none_for_noncompiler_command(self) -> None:
        result = GCCCompilerCommandParser().parse(
            "ar rcs lib.a main.o", "/repo", "/repo", "build-1"
        )
        self.assertIsNone(result)

    def test_compiler_version_probe_uses_read_only_command_runner(self) -> None:
        runner = MetadataRunner()
        version = GCCCompilerMetadataProvider(runner).version("gcc", "/repo")
        self.assertEqual("gcc (GCC) 12.2.0", version)
        self.assertEqual(("gcc", "--version"), runner.request.arguments)
        self.assertEqual("read_only", runner.request.risk.value)
