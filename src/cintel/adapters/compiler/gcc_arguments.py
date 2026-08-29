from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
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
        consumer = _WRAPPER_CONSUMERS.get(basename)
        if consumer is not None:
            launchers.append(tokens[index])
            index = consumer(tokens, index + 1, launchers)
            continue
        return None, tuple(launchers)
    return None, tuple(launchers)


def _consume_env(tokens: list[str], index: int, launchers: list[str]) -> int:
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
    return index


def _consume_nice(tokens: list[str], index: int, launchers: list[str]) -> int:
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
    return index


def _consume_time(tokens: list[str], index: int, launchers: list[str]) -> int:
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
    return index


_WRAPPER_CONSUMERS = {
    "env": _consume_env,
    "nice": _consume_nice,
    "time": _consume_time,
}


@dataclass
class _ArgumentAccumulator:
    include_paths: list[IncludePath] = field(default_factory=list)
    defines: list[MacroDefinition] = field(default_factory=list)
    undefines: list[str] = field(default_factory=list)
    forced_includes: list[PathReference] = field(default_factory=list)
    optimization: list[str] = field(default_factory=list)
    debug: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    architecture: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    sources: list[PathReference] = field(default_factory=list)
    object_file: PathReference | None = None
    language_standard: str | None = None


def _parse_arguments(
    arguments: tuple[str, ...], working_directory: Path, repository_root: Path
) -> tuple[
    CompilerArgumentSet,
    list[PathReference],
    PathReference | None,
    tuple[Diagnostic, ...],
]:
    accumulator = _ArgumentAccumulator()
    diagnostics: list[Diagnostic] = []
    index = 0
    while index < len(arguments):
        index = _classify_argument(
            arguments, index, working_directory, repository_root, accumulator, diagnostics
        )
    return (
        CompilerArgumentSet(
            include_paths=tuple(accumulator.include_paths),
            defines=tuple(accumulator.defines),
            undefines=tuple(accumulator.undefines),
            forced_includes=tuple(accumulator.forced_includes),
            language_standard=accumulator.language_standard,
            optimization_flags=tuple(accumulator.optimization),
            debug_flags=tuple(accumulator.debug),
            warning_flags=tuple(accumulator.warnings),
            architecture_flags=tuple(accumulator.architecture),
            dependency_flags=tuple(accumulator.dependency),
            unclassified_arguments=tuple(accumulator.unclassified),
        ),
        accumulator.sources,
        accumulator.object_file,
        tuple(diagnostics),
    )


def _classify_argument(
    arguments: tuple[str, ...],
    index: int,
    working_directory: Path,
    repository_root: Path,
    accumulator: _ArgumentAccumulator,
    diagnostics: list[Diagnostic],
) -> int:
    token = arguments[index]
    for handler in _ARGUMENT_HANDLERS:
        next_index = handler(
            arguments, index, token, working_directory, repository_root, accumulator, diagnostics
        )
        if next_index is not None:
            return next_index
    accumulator.unclassified.append(token)
    return index + 1


def _missing_value_diagnostic(token: str) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.COMPILER_OPTION_MISSING_VALUE,
        severity=DiagnosticSeverity.WARNING,
        message=f"Compiler option {token} is missing its value.",
        technical_details="The original argument list was preserved.",
        missing_capability="exact_compiler_arguments",
        recoverability=Recoverability.REDUCED_CAPABILITY,
    )


def _missing_value(
    token: str,
    index: int,
    accumulator: _ArgumentAccumulator,
    diagnostics: list[Diagnostic],
) -> int:
    diagnostics.append(_missing_value_diagnostic(token))
    accumulator.unclassified.append(token)
    return index + 1


def _handle_include_flags(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token == "-I":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        accumulator.include_paths.append(
            IncludePath(_path_reference(arguments[index + 1], working_directory, repository_root))
        )
        return index + 2
    if token.startswith("-I") and token != "-I":
        accumulator.include_paths.append(
            IncludePath(_path_reference(token[2:], working_directory, repository_root))
        )
        return index + 1
    if token == "-isystem":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        accumulator.include_paths.append(
            IncludePath(
                _path_reference(arguments[index + 1], working_directory, repository_root),
                is_system=True,
            )
        )
        return index + 2
    if token.startswith("-isystem") and token != "-isystem":
        accumulator.include_paths.append(
            IncludePath(
                _path_reference(token[len("-isystem") :], working_directory, repository_root),
                is_system=True,
            )
        )
        return index + 1
    return None


def _handle_define_flags(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token == "-D" or token == "-U":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        value = arguments[index + 1]
        if token == "-D":
            accumulator.defines.append(_macro_definition(value))
        else:
            accumulator.undefines.append(value)
        return index + 2
    if token.startswith("-D") and token != "-D":
        accumulator.defines.append(_macro_definition(token[2:]))
        return index + 1
    if token.startswith("-U") and token != "-U":
        accumulator.undefines.append(token[2:])
        return index + 1
    return None


def _handle_forced_includes(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token == "-include":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        accumulator.forced_includes.append(
            _path_reference(arguments[index + 1], working_directory, repository_root)
        )
        return index + 2
    if token.startswith("-include") and token != "-include":
        accumulator.forced_includes.append(
            _path_reference(token[len("-include") :], working_directory, repository_root)
        )
        return index + 1
    return None


def _handle_standard(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token.startswith("-std="):
        accumulator.language_standard = token.split("=", 1)[1]
        return index + 1
    if token == "-std":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        accumulator.language_standard = arguments[index + 1]
        return index + 2
    return None


def _handle_output(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token == "-o":
        if index + 1 >= len(arguments):
            return _missing_value(token, index, accumulator, diagnostics)
        accumulator.object_file = _path_reference(
            arguments[index + 1], working_directory, repository_root
        )
        return index + 2
    if token.startswith("-o") and token != "-o":
        accumulator.object_file = _path_reference(token[2:], working_directory, repository_root)
        return index + 1
    return None


def _handle_sources(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token.endswith(".c") and not token.startswith("-"):
        accumulator.sources.append(
            _path_reference(token, working_directory, repository_root)
        )
        return index + 1
    return None


def _handle_simple_flags(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token.startswith("-O"):
        accumulator.optimization.append(token)
        return index + 1
    if token == "-g" or token.startswith("-g"):
        accumulator.debug.append(token)
        return index + 1
    if token.startswith("-W"):
        accumulator.warnings.append(token)
        return index + 1
    if token.startswith("-m") or token in {"-pthread", "-fPIC", "-fpic"}:
        accumulator.architecture.append(token)
        return index + 1
    return None


def _handle_dependency_flags(
    arguments, index, token, working_directory, repository_root, accumulator, diagnostics
) -> int | None:
    if token in {"-M", "-MM", "-MD", "-MMD", "-MP", "-MG"}:
        accumulator.dependency.append(token)
        return index + 1
    if token in {"-MF", "-MT", "-MQ"}:
        accumulator.dependency.append(token)
        if index + 1 < len(arguments):
            accumulator.dependency.append(arguments[index + 1])
            return index + 2
        diagnostics.append(_missing_value_diagnostic(token))
        return index + 1
    return None


_ARGUMENT_HANDLERS = (
    _handle_include_flags,
    _handle_define_flags,
    _handle_forced_includes,
    _handle_standard,
    _handle_output,
    _handle_sources,
    _handle_simple_flags,
    _handle_dependency_flags,
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
