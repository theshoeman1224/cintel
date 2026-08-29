from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CapabilityStatus,
    CommandClassification,
    ProcessExitCode,
    CommandRequest,
    CommandResult,
    CommandRisk,
    CompilationUnit,
    CompilerInvocation,
    RawBuildCommand,
    replace_fields,
)
from cintel.ports.commands import CommandRunner
from cintel.ports.services import CompilerCommandParser, CompilerMetadataProvider
from cintel.utilities.hashing import stable_fingerprint, stable_id

_ENTERING = re.compile(
    r"^g?make(?:\[\d+\])?: Entering directory [`'\u2018\u2019](.+?)[`'\u2018\u2019]$"
)
_LEAVING = re.compile(
    r"^g?make(?:\[\d+\])?: Leaving directory [`'\u2018\u2019](.+?)[`'\u2018\u2019]$"
)


@dataclass(frozen=True, slots=True)
class ParsedMakeOutput:
    """Everything one Make dry-run transcript yields, without positional unpacking."""

    commands: tuple[RawBuildCommand, ...]
    compiler_invocations: tuple[CompilerInvocation, ...]
    compilation_units: tuple[CompilationUnit, ...]
    diagnostics: tuple[Diagnostic, ...]


class MakeBuildDiscovery:
    def __init__(
        self,
        command_runner: CommandRunner,
        compiler_parser: CompilerCommandParser,
        compiler_metadata: CompilerMetadataProvider | None = None,
    ) -> None:
        self._command_runner = command_runner
        self._compiler_parser = compiler_parser
        self._compiler_metadata = compiler_metadata

    def command_request(self, configuration: BuildConfiguration) -> CommandRequest:
        return CommandRequest(
            arguments=make_dry_run_arguments(configuration),
            working_directory=configuration.working_directory
            or configuration.repository_root,
            environment_overrides=configuration.environment_overrides,
            timeout_seconds=120,
            risk=CommandRisk.MAKEFILE_EVALUATION,
        )

    def input_fingerprint(self, configuration: BuildConfiguration) -> str:
        return build_discovery_input_fingerprint(configuration)

    def discover(self, configuration: BuildConfiguration) -> BuildDiscoveryResult:
        request = self.command_request(configuration)
        result = self._command_runner.run(request)
        return self._build_result(configuration, request, result)

    def _build_result(
        self,
        configuration: BuildConfiguration,
        request: CommandRequest,
        result: CommandResult,
    ) -> BuildDiscoveryResult:
        parsed = self.parse_output(configuration, result.standard_output)
        diagnostics = _execution_diagnostics(configuration, result, parsed)
        input_fingerprint = self.input_fingerprint(configuration)
        compiler_versions = self._compiler_versions(parsed.compiler_invocations)
        build_fingerprint = stable_fingerprint(
            {
                "input_fingerprint": input_fingerprint,
                "compiler_executables": sorted(
                    {item.compiler_executable for item in parsed.compiler_invocations}
                ),
                "compiler_versions": compiler_versions,
                "normalized_compiler_commands": [
                    {
                        "compiler": item.compiler_executable,
                        "arguments": item.raw_arguments,
                        "working_directory": item.working_directory,
                    }
                    for item in parsed.compiler_invocations
                ],
            }
        )
        return BuildDiscoveryResult(
            configuration=configuration,
            make_arguments=request.arguments,
            raw_output=result.standard_output,
            raw_error=result.standard_error,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            commands=parsed.commands,
            compiler_invocations=parsed.compiler_invocations,
            compilation_units=parsed.compilation_units,
            diagnostics=tuple(diagnostics),
            capabilities=_capability_records(
                result.exit_code, parsed, compiler_versions
            ),
            input_fingerprint=input_fingerprint,
            build_fingerprint=build_fingerprint,
            discovered_at=datetime.now(timezone.utc),
            compiler_versions=compiler_versions,
            selected_source_files=tuple(
                sorted(
                    {
                        item.source.absolute
                        for item in parsed.compiler_invocations
                        if item.source is not None
                        and Path(item.source.absolute).is_file()
                    }
                )
            ),
            missing_source_files=tuple(
                sorted(
                    {
                        item.source.absolute
                        for item in parsed.compiler_invocations
                        if item.source is not None
                        and not Path(item.source.absolute).is_file()
                    }
                )
            ),
        )

    def discover_from_output(
        self,
        configuration: BuildConfiguration,
        raw_output: str,
        *,
        raw_error: str = "",
        exit_code: int = 0,
        artifact_hash: str | None = None,
    ) -> BuildDiscoveryResult:
        """Parse validated saved output through the same path as live Make output."""
        request = self.command_request(configuration)
        result = self._build_result(
            configuration,
            request,
            CommandResult(
                standard_output=raw_output,
                standard_error=raw_error,
                exit_code=exit_code,
                duration_seconds=0.0,
                executed_command=request.arguments,
                effective_working_directory=request.working_directory,
            ),
        )
        input_fingerprint = stable_fingerprint(
            {
                "configuration": result.input_fingerprint,
                "saved_artifact": artifact_hash or stable_fingerprint(raw_output),
            }
        )
        return replace_fields(
            result,
            input_fingerprint=input_fingerprint,
            build_fingerprint=stable_fingerprint(
                {
                    "parsed_build": result.build_fingerprint,
                    "saved_artifact": artifact_hash or stable_fingerprint(raw_output),
                }
            ),
        )

    def _compiler_versions(
        self, invocations: tuple[CompilerInvocation, ...]
    ) -> tuple[tuple[str, str], ...]:
        versions: list[tuple[str, str]] = []
        for executable in sorted({item.compiler_executable for item in invocations}):
            version: str | None = None
            if self._compiler_metadata is not None:
                working_directory = next(
                    item.working_directory
                    for item in invocations
                    if item.compiler_executable == executable
                )
                version = self._compiler_metadata.version(executable, working_directory)
            versions.append((executable, version or "unavailable"))
        return tuple(versions)

    def parse_output(
        self, configuration: BuildConfiguration, raw_output: str
    ) -> ParsedMakeOutput:
        initial_directory = Path(
            configuration.working_directory or configuration.repository_root
        ).resolve()
        directory_stack = [initial_directory]
        commands: list[RawBuildCommand] = []
        invocations: list[CompilerInvocation] = []
        units: list[CompilationUnit] = []
        diagnostics: list[Diagnostic] = []

        for line in _logical_lines(raw_output):
            stripped = line.strip()
            if not stripped:
                continue
            entering = _ENTERING.match(stripped)
            if entering:
                entered = Path(entering.group(1))
                if not entered.is_absolute():
                    entered = directory_stack[-1] / entered
                directory_stack.append(entered.resolve())
                continue
            leaving = _LEAVING.match(stripped)
            if leaving:
                if len(directory_stack) > 1:
                    directory_stack.pop()
                else:
                    diagnostics.append(
                        _build_parse_diagnostic(
                            stripped, "Make directory stack underflow"
                        )
                    )
                continue
            if _is_make_message(stripped):
                continue

            self._process_command_line(
                stripped,
                directory_stack[-1],
                configuration,
                commands,
                invocations,
                units,
                diagnostics,
            )
        return ParsedMakeOutput(
            commands=tuple(commands),
            compiler_invocations=tuple(
                {item.id: item for item in invocations}.values()
            ),
            compilation_units=tuple({item.id: item for item in units}.values()),
            diagnostics=tuple(diagnostics),
        )

    def _process_command_line(
        self,
        stripped: str,
        stack_top: Path,
        configuration: BuildConfiguration,
        commands: list[RawBuildCommand],
        invocations: list[CompilerInvocation],
        units: list[CompilationUnit],
        diagnostics: list[Diagnostic],
    ) -> None:
        effective_directory = stack_top
        for segment in _split_shell_commands(stripped):
            raw_segment = segment.strip()
            if not raw_segment:
                continue
            raw_segment = raw_segment.lstrip("@+").strip()
            try:
                tokens = shlex.split(raw_segment, posix=True)
            except ValueError as error:
                diagnostic = _build_parse_diagnostic(raw_segment, str(error))
                diagnostics.append(diagnostic)
                commands.append(
                    RawBuildCommand(
                        raw_content=raw_segment,
                        working_directory=str(effective_directory),
                        classification=CommandClassification.UNPARSED,
                        parse_diagnostic=diagnostic,
                    )
                )
                continue
            if _is_cd(tokens):
                effective_directory = _change_directory(
                    tokens, stack_top, effective_directory, raw_segment, commands
                )
                continue
            parsed = self._compiler_parser.parse(
                raw_segment,
                str(effective_directory),
                configuration.repository_root,
                configuration.id,
            )
            if parsed is not None:
                commands.append(
                    RawBuildCommand(
                        raw_content=raw_segment,
                        working_directory=str(effective_directory),
                        classification=CommandClassification.COMPILER,
                    )
                )
                self._record_parsed_invocations(
                    parsed, configuration, invocations, units, diagnostics
                )
                continue
            commands.append(
                RawBuildCommand(
                    raw_content=raw_segment,
                    working_directory=str(effective_directory),
                    classification=_non_compiler_classification(tokens),
                )
            )

    def _record_parsed_invocations(
        self,
        parsed: tuple[CompilerInvocation, ...],
        configuration: BuildConfiguration,
        invocations: list[CompilerInvocation],
        units: list[CompilationUnit],
        diagnostics: list[Diagnostic],
    ) -> None:
        for invocation in parsed:
            invocations.append(invocation)
            diagnostics.extend(invocation.parse_diagnostics)
            self._record_invocation(invocation, configuration, units, diagnostics)

    def _record_invocation(
        self,
        invocation: CompilerInvocation,
        configuration: BuildConfiguration,
        units: list[CompilationUnit],
        diagnostics: list[Diagnostic],
    ) -> None:
        for forced_include in invocation.arguments.forced_includes:
            if not Path(forced_include.absolute).is_file():
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.MISSING_FORCED_INCLUDE,
                        severity=DiagnosticSeverity.WARNING,
                        message=(
                            "A compiler command references a missing forced include."
                        ),
                        technical_details=(
                            "The header may be generated or the build "
                            "environment may be incomplete."
                        ),
                        missing_capability="complete_compilation_unit",
                        recoverability=Recoverability.USER_ACTION,
                        suggested_actions=(
                            "Generate or provide the forced include, then rerun build discovery.",
                        ),
                        related_paths=(forced_include.absolute,),
                    )
                )
        if invocation.source is None:
            return
        source_exists = Path(invocation.source.absolute).is_file()
        source_file_id = (
            stable_id(
                "file",
                configuration.repository_id,
                invocation.source.repository_relative,
            )
            if source_exists
            and invocation.source.repository_relative is not None
            else None
        )
        if not source_exists:
            diagnostics.append(
                Diagnostic(
                    code=DiagnosticCode.MISSING_SOURCE_FILE,
                    severity=DiagnosticSeverity.WARNING,
                    message="A compiler command references a missing source file.",
                    technical_details=(
                        "The file may be generated or the build environment may be incomplete."
                    ),
                    missing_capability="complete_compilation_unit",
                    recoverability=Recoverability.USER_ACTION,
                    suggested_actions=(
                        "Generate or provide the referenced source, then rerun build discovery.",
                    ),
                    related_paths=(invocation.source.absolute,),
                )
            )
        fingerprint = stable_fingerprint(
            {
                "source": invocation.source.absolute,
                "compiler": invocation.compiler_executable,
                "arguments": invocation.raw_arguments,
                "working_directory": invocation.working_directory,
                "build_configuration": configuration.id,
            }
        )
        units.append(
            CompilationUnit(
                id=stable_id("compilation-unit", fingerprint),
                repository_id=configuration.repository_id,
                build_configuration_id=configuration.id,
                source_file_id=source_file_id,
                compiler_invocation=invocation,
                fingerprint=fingerprint,
            )
        )


def _execution_diagnostics(
    configuration: BuildConfiguration,
    result: CommandResult,
    parsed: ParsedMakeOutput,
) -> list[Diagnostic]:
    diagnostics = list(parsed.diagnostics)
    if result.exit_code == ProcessExitCode.COMMAND_NOT_FOUND:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.MAKE_NOT_EXECUTABLE,
                severity=DiagnosticSeverity.ERROR,
                message="GNU Make could not be executed.",
                technical_details=result.standard_error,
                missing_capability="make_build_discovery",
                recoverability=Recoverability.USER_ACTION,
                suggested_actions=(
                    "Install GNU Make or provide saved dry-run output in a later recovery workflow.",
                ),
                related_commands=(),
            )
        )
    elif result.exit_code != 0:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.MAKE_DRY_RUN_INCOMPLETE,
                severity=DiagnosticSeverity.WARNING,
                message="GNU Make dry-run evaluation did not complete successfully.",
                technical_details=(
                    f"Exit code {result.exit_code}. {result.standard_error.strip()}"
                ).strip(),
                missing_capability="complete_make_build_discovery",
                recoverability=Recoverability.REDUCED_CAPABILITY,
                suggested_actions=(
                    "Review the Make output and provide missing generated files or variables.",
                ),
                related_paths=(configuration.makefile,) if configuration.makefile else (),
            )
        )
    if not parsed.compiler_invocations:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.NO_COMPILER_RECOGNIZED,
                severity=DiagnosticSeverity.WARNING,
                message="No recognizable C compiler command was found in Make output.",
                technical_details="The raw dry-run output and other commands were preserved.",
                missing_capability="compilation_units",
                recoverability=Recoverability.REDUCED_CAPABILITY,
                suggested_actions=(
                    "Check the target and Make variables or use a verbose build recipe.",
                ),
            )
        )
    return diagnostics


def _capability_records(
    exit_code: int,
    parsed: ParsedMakeOutput,
    compiler_versions: tuple[tuple[str, str], ...],
) -> tuple[AnalysisCapability, ...]:
    units = parsed.compilation_units
    parse_diagnostics = parsed.diagnostics

    if exit_code == ProcessExitCode.COMMAND_NOT_FOUND:
        discovery_status = CapabilityStatus.UNAVAILABLE
    elif exit_code != 0 or not units or parse_diagnostics:
        discovery_status = CapabilityStatus.DEGRADED
    else:
        discovery_status = CapabilityStatus.AVAILABLE

    if units and not parse_diagnostics:
        flags_status = CapabilityStatus.AVAILABLE
    elif units:
        flags_status = CapabilityStatus.DEGRADED
    else:
        flags_status = CapabilityStatus.UNAVAILABLE

    if compiler_versions and all(
        version != "unavailable" for _, version in compiler_versions
    ):
        version_status = CapabilityStatus.AVAILABLE
    elif compiler_versions:
        version_status = CapabilityStatus.DEGRADED
    else:
        version_status = CapabilityStatus.UNAVAILABLE

    return (
        AnalysisCapability(
            name="make_build_discovery",
            status=discovery_status,
            reason=(
                "Make dry-run output produced compilation units."
                if units
                else "Make dry-run output did not produce usable compilation units."
            ),
            evidence=(
                f"{len(parsed.commands)} shell commands preserved",
                f"{len(parsed.compiler_invocations)} compiler invocations recognized",
                f"{len(units)} compilation units created",
            ),
        ),
        AnalysisCapability(
            name="exact_compiler_flags",
            status=flags_status,
            reason="Arguments are extracted conservatively from observed compiler commands.",
        ),
        AnalysisCapability(
            name="compiler_version_fingerprint",
            status=version_status,
            reason=(
                "Available compiler versions are included in the build fingerprint."
                if compiler_versions
                else "No compiler executable was available to identify."
            ),
        ),
    )


def _change_directory(
    tokens: list[str],
    stack_top: Path,
    effective_directory: Path,
    raw_segment: str,
    commands: list[RawBuildCommand],
) -> Path:
    target = Path(tokens[1])
    if not target.is_absolute():
        target = effective_directory / target
    resolved = target.resolve()
    commands.append(
        RawBuildCommand(
            raw_content=raw_segment,
            working_directory=str(stack_top),
            classification=CommandClassification.DIRECTORY_CHANGE,
        )
    )
    return resolved


def _non_compiler_classification(tokens: list[str]) -> CommandClassification:
    return (
        CommandClassification.RECURSIVE_MAKE
        if _is_recursive_make(tokens)
        else CommandClassification.OTHER
    )


def make_dry_run_arguments(configuration: BuildConfiguration) -> tuple[str, ...]:
    arguments = ["make", "-n"]
    if not configuration.respect_make_timestamps:
        arguments.append("-B")
    if configuration.makefile:
        arguments.extend(("-f", configuration.makefile))
    if configuration.target:
        arguments.append(configuration.target)
    arguments.extend(f"{name}={value}" for name, value in configuration.make_variables)
    return tuple(arguments)


def build_discovery_input_fingerprint(configuration: BuildConfiguration) -> str:
    return stable_fingerprint(
        {
            "repository": configuration.repository_root,
            "build_configuration": configuration.name,
            "makefile": configuration.makefile,
            "working_directory": configuration.working_directory,
            "target": configuration.target,
            "make_variables": configuration.make_variables,
            "environment_overrides": configuration.environment_overrides,
            "build_input_hashes": configuration.build_input_hashes,
            "respect_make_timestamps": configuration.respect_make_timestamps,
        }
    )


def _logical_lines(raw_output: str) -> tuple[str, ...]:
    lines: list[str] = []
    pending = ""
    for physical in raw_output.splitlines():
        value = f"{pending}{physical}" if pending else physical
        if value.rstrip().endswith("\\"):
            pending = value.rstrip()[:-1] + " "
            continue
        lines.append(value)
        pending = ""
    if pending:
        lines.append(pending)
    return tuple(lines)


def _split_shell_commands(value: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(value):
        character = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            index += 1
            continue
        if quote is None and character == ";":
            parts.append(value[start:index])
            start = index + 1
        elif (
            quote is None
            and character == "&"
            and index + 1 < len(value)
            and value[index + 1] == "&"
        ):
            parts.append(value[start:index])
            start = index + 2
            index += 1
        index += 1
    parts.append(value[start:])
    return tuple(parts)


def _is_cd(tokens: list[str]) -> bool:
    return len(tokens) == 2 and tokens[0] == "cd" and tokens[1] != "-"


def _is_recursive_make(tokens: list[str]) -> bool:
    index = 0
    while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("-"):
        index += 1
    return index < len(tokens) and Path(tokens[index]).name in {"make", "gmake"}


def _is_make_message(value: str) -> bool:
    return value.startswith(("make:", "make[", "gmake:", "gmake["))


def _build_parse_diagnostic(raw: str, detail: str) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.COMMAND_UNPARSEABLE,
        severity=DiagnosticSeverity.WARNING,
        message="A Make dry-run command could not be parsed safely.",
        technical_details=f"{detail}: {raw}",
        missing_capability="complete_command_discovery",
        recoverability=Recoverability.REDUCED_CAPABILITY,
        suggested_actions=("Inspect the preserved raw Make output.",),
    )
