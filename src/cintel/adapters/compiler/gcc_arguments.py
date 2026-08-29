from __future__ import annotations

import re
import shlex
from pathlib import Path

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    CompilerArgumentSet,
    CompilerInvocation,
    IncludePath,
    MacroDefinition,
    PathReference,
)
from cintel.utilities.hashing import stable_fingerprint, stable_id
from cintel.utilities.paths import normalized_path, repository_relative

_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=.*$", re.DOTALL)
_COMPILER = re.compile(r"^(?:[A-Za-z0-9_.+-]+-)?(?:gcc|cc|clang)$")
_SIMPLE_WRAPPERS = {"ccache", "distcc", "sccache"}


class GCCCompilerCommandParser:
    """Parse GCC-like compile commands without invoking a compiler."""

    def parse(
        self,
        raw_command: str,
        working_directory: str,
        repository_root: str,
        build_configuration_id: str,
    ) -> tuple[CompilerInvocation, ...] | None:
        tokens = shlex.split(raw_command, posix=True)
        compiler_index, launchers = _find_compiler(tokens)
        if compiler_index is None:
            return None
        compiler = tokens[compiler_index]
        raw_arguments = tuple(tokens[compiler_index + 1 :])
        parsed, sources, object_file, diagnostics = _parse_arguments(
            raw_arguments, Path(working_directory), Path(repository_root)
        )
        source_references = sources or [None]
        invocations: list[CompilerInvocation] = []
        for source in source_references:
            identity = stable_fingerprint(
                {
                    "compiler": compiler,
                    "arguments": raw_arguments,
                    "working_directory": str(Path(working_directory).resolve()),
                    "source": source.absolute if source else None,
                    "build_configuration": build_configuration_id,
                }
            )
            invocations.append(
                CompilerInvocation(
                    id=stable_id("compiler-invocation", identity),
                    compiler_executable=compiler,
                    launchers=launchers,
                    source=source,
                    object_file=object_file,
                    working_directory=str(Path(working_directory).resolve()),
                    raw_command=raw_command,
                    raw_arguments=raw_arguments,
                    arguments=parsed,
                    parse_diagnostics=diagnostics,
                )
            )
        return tuple(invocations)


def _find_compiler(tokens: list[str]) -> tuple[int | None, tuple[str, ...]]:
    index = 0
    launchers: list[str] = []
    while index < len(tokens) and _ASSIGNMENT.match(tokens[index]):
        launchers.append(tokens[index])
        index += 1

    while index < len(tokens):
        basename = Path(tokens[index]).name
        if _COMPILER.match(basename):
            return index, tuple(launchers)
        if basename in _SIMPLE_WRAPPERS:
            launchers.append(tokens[index])
            index += 1
            continue
        if basename == "env":
            launchers.append(tokens[index])
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if _ASSIGNMENT.match(token) or token in {"-i", "--ignore-environment"}:
                    launchers.append(token)
                    index += 1
                    continue
                if token in {"-u", "--unset"} and index + 1 < len(tokens):
                    launchers.extend(tokens[index : index + 2])
                    index += 2
                    continue
                if token.startswith("--unset="):
                    launchers.append(token)
                    index += 1
                    continue
                break
            continue
        if basename == "nice":
            launchers.append(tokens[index])
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if token in {"-n", "--adjustment"} and index + 1 < len(tokens):
                    launchers.extend(tokens[index : index + 2])
                    index += 2
                elif token.startswith("--adjustment="):
                    launchers.append(token)
                    index += 1
                else:
                    break
            continue
        if basename == "time":
            launchers.append(tokens[index])
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if token in {"-o", "--output", "-f", "--format"} and index + 1 < len(tokens):
                    launchers.extend(tokens[index : index + 2])
                    index += 2
                elif token.startswith("-"):
                    launchers.append(token)
                    index += 1
                else:
                    break
            continue
        return None, tuple(launchers)
    return None, tuple(launchers)


def _parse_arguments(
    arguments: tuple[str, ...], working_directory: Path, repository_root: Path
) -> tuple[
    CompilerArgumentSet,
    list[PathReference],
    PathReference | None,
    tuple[Diagnostic, ...],
]:
    include_paths: list[IncludePath] = []
    defines: list[MacroDefinition] = []
    undefines: list[str] = []
    forced_includes: list[PathReference] = []
    optimization: list[str] = []
    debug: list[str] = []
    warnings: list[str] = []
    architecture: list[str] = []
    dependency: list[str] = []
    unclassified: list[str] = []
    sources: list[PathReference] = []
    object_file: PathReference | None = None
    language_standard: str | None = None
    diagnostics: list[Diagnostic] = []
    index = 0

    def missing(flag: str) -> None:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.COMPILER_OPTION_MISSING_VALUE,
                severity=DiagnosticSeverity.WARNING,
                message=f"Compiler option {flag} is missing its value.",
                technical_details="The original argument list was preserved.",
                missing_capability="exact_compiler_arguments",
                recoverability=Recoverability.REDUCED_CAPABILITY,
            )
        )

    while index < len(arguments):
        token = arguments[index]
        if token == "-I":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            include_paths.append(
                IncludePath(_path_reference(arguments[index + 1], working_directory, repository_root))
            )
            index += 2
            continue
        if token.startswith("-I") and token != "-I":
            include_paths.append(
                IncludePath(_path_reference(token[2:], working_directory, repository_root))
            )
            index += 1
            continue
        if token == "-isystem":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            include_paths.append(
                IncludePath(
                    _path_reference(arguments[index + 1], working_directory, repository_root),
                    is_system=True,
                )
            )
            index += 2
            continue
        if token.startswith("-isystem") and token != "-isystem":
            include_paths.append(
                IncludePath(
                    _path_reference(token[len("-isystem") :], working_directory, repository_root),
                    is_system=True,
                )
            )
            index += 1
            continue
        if token == "-D" or token == "-U":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            value = arguments[index + 1]
            if token == "-D":
                defines.append(_macro_definition(value))
            else:
                undefines.append(value)
            index += 2
            continue
        if token.startswith("-D") and token != "-D":
            defines.append(_macro_definition(token[2:]))
            index += 1
            continue
        if token.startswith("-U") and token != "-U":
            undefines.append(token[2:])
            index += 1
            continue
        if token == "-include":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            forced_includes.append(
                _path_reference(arguments[index + 1], working_directory, repository_root)
            )
            index += 2
            continue
        if token.startswith("-include") and token != "-include":
            forced_includes.append(
                _path_reference(token[len("-include") :], working_directory, repository_root)
            )
            index += 1
            continue
        if token.startswith("-std="):
            language_standard = token.split("=", 1)[1]
            index += 1
            continue
        if token == "-std":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            language_standard = arguments[index + 1]
            index += 2
            continue
        if token == "-o":
            if index + 1 >= len(arguments):
                missing(token)
                unclassified.append(token)
                index += 1
                continue
            object_file = _path_reference(
                arguments[index + 1], working_directory, repository_root
            )
            index += 2
            continue
        if token.startswith("-o") and token != "-o":
            object_file = _path_reference(token[2:], working_directory, repository_root)
            index += 1
            continue
        if token.endswith(".c") and not token.startswith("-"):
            sources.append(_path_reference(token, working_directory, repository_root))
            index += 1
            continue
        if token.startswith("-O"):
            optimization.append(token)
            index += 1
            continue
        if token == "-g" or token.startswith("-g"):
            debug.append(token)
            index += 1
            continue
        if token.startswith("-W"):
            warnings.append(token)
            index += 1
            continue
        if token.startswith("-m") or token in {"-pthread", "-fPIC", "-fpic"}:
            architecture.append(token)
            index += 1
            continue
        if token in {"-M", "-MM", "-MD", "-MMD", "-MP", "-MG"}:
            dependency.append(token)
            index += 1
            continue
        if token in {"-MF", "-MT", "-MQ"}:
            dependency.append(token)
            if index + 1 < len(arguments):
                dependency.append(arguments[index + 1])
                index += 2
            else:
                missing(token)
                index += 1
            continue
        unclassified.append(token)
        index += 1

    return (
        CompilerArgumentSet(
            include_paths=tuple(include_paths),
            defines=tuple(defines),
            undefines=tuple(undefines),
            forced_includes=tuple(forced_includes),
            language_standard=language_standard,
            optimization_flags=tuple(optimization),
            debug_flags=tuple(debug),
            warning_flags=tuple(warnings),
            architecture_flags=tuple(architecture),
            dependency_flags=tuple(dependency),
            unclassified_arguments=tuple(unclassified),
        ),
        sources,
        object_file,
        tuple(diagnostics),
    )


def _path_reference(
    value: str, working_directory: Path, repository_root: Path
) -> PathReference:
    absolute = normalized_path(Path(value), working_directory)
    return PathReference(
        original=value,
        absolute=str(absolute),
        repository_relative=repository_relative(absolute, repository_root),
    )


def _macro_definition(value: str) -> MacroDefinition:
    if "=" in value:
        name, replacement = value.split("=", 1)
        return MacroDefinition(name=name, value=replacement)
    return MacroDefinition(name=value)
