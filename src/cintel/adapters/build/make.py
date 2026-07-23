from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity, Recoverability
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CapabilityStatus,
    CommandRequest,
    CommandRisk,
    CompilationUnit,
    CompilerInvocation,
    RawBuildCommand,
)
from cintel.ports.commands import CommandRunner
from cintel.ports.services import CompilerCommandParser, CompilerMetadataProvider
from cintel.utilities.hashing import stable_fingerprint, stable_id

_ENTERING = re.compile(
    r"^(?:g?make)(?:\[\d+\])?: Entering directory [`'\u2018\u2019](.+?)[`'\u2018\u2019]$"
)
_LEAVING = re.compile(
    r"^(?:g?make)(?:\[\d+\])?: Leaving directory [`'\u2018\u2019](.+?)[`'\u2018\u2019]$"
)


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
        arguments = list(make_dry_run_arguments(configuration))
        return CommandRequest(
            arguments=tuple(arguments),
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
        (
            commands,
            invocations,
            units,
            parse_diagnostics,
        ) = self.parse_output(configuration, result.standard_output)
        diagnostics = list(parse_diagnostics)
        if result.exit_code == 127:
            diagnostics.append(
                Diagnostic(
                    code="CI-BUILD-001",
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
                    code="CI-BUILD-002",
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
        if not invocations:
            diagnostics.append(
                Diagnostic(
                    code="CI-COMP-001",
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

        input_fingerprint = self.input_fingerprint(configuration)
        compiler_versions = tuple(
            (
                executable,
                (
                    self._compiler_metadata.version(
                        executable,
                        next(
                            item.working_directory
                            for item in invocations
                            if item.compiler_executable == executable
                        ),
                    )
                    if self._compiler_metadata is not None
                    else None
                )
                or "unavailable",
            )
            for executable in sorted(
                {item.compiler_executable for item in invocations}
            )
        )
        build_fingerprint = stable_fingerprint(
            {
                "input_fingerprint": input_fingerprint,
                "compiler_executables": sorted(
                    {item.compiler_executable for item in invocations}
                ),
                "compiler_versions": compiler_versions,
                "normalized_compiler_commands": [
                    {
                        "compiler": item.compiler_executable,
                        "arguments": item.raw_arguments,
                        "working_directory": item.working_directory,
                    }
                    for item in invocations
                ],
            }
        )
        capability_status = (
            CapabilityStatus.UNAVAILABLE
            if result.exit_code == 127
            else CapabilityStatus.DEGRADED
            if result.exit_code != 0 or not units or parse_diagnostics
            else CapabilityStatus.AVAILABLE
        )
        capabilities = (
            AnalysisCapability(
                name="make_build_discovery",
                status=capability_status,
                reason=(
                    "Make dry-run output produced compilation units."
                    if units
                    else "Make dry-run output did not produce usable compilation units."
                ),
                evidence=(
                    f"{len(commands)} shell commands preserved",
                    f"{len(invocations)} compiler invocations recognized",
                    f"{len(units)} compilation units created",
                ),
            ),
            AnalysisCapability(
                name="exact_compiler_flags",
                status=(
                    CapabilityStatus.AVAILABLE
                    if units and not parse_diagnostics
                    else CapabilityStatus.DEGRADED
                    if units
                    else CapabilityStatus.UNAVAILABLE
                ),
                reason="Arguments are extracted conservatively from observed compiler commands.",
            ),
            AnalysisCapability(
                name="compiler_version_fingerprint",
                status=(
                    CapabilityStatus.AVAILABLE
                    if compiler_versions
                    and all(version != "unavailable" for _, version in compiler_versions)
                    else CapabilityStatus.DEGRADED
                    if compiler_versions
                    else CapabilityStatus.UNAVAILABLE
                ),
                reason=(
                    "Available compiler versions are included in the build fingerprint."
                    if compiler_versions
                    else "No compiler executable was available to identify."
                ),
            ),
        )
        return BuildDiscoveryResult(
            configuration=configuration,
            make_arguments=request.arguments,
            raw_output=result.standard_output,
            raw_error=result.standard_error,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            commands=commands,
            compiler_invocations=invocations,
            compilation_units=units,
            diagnostics=tuple(diagnostics),
            capabilities=capabilities,
            input_fingerprint=input_fingerprint,
            build_fingerprint=build_fingerprint,
            discovered_at=datetime.now(timezone.utc),
            compiler_versions=compiler_versions,
            selected_source_files=tuple(
                sorted(
                    {
                        item.source.absolute
                        for item in invocations
                        if item.source is not None
                        and Path(item.source.absolute).is_file()
                    }
                )
            ),
            missing_source_files=tuple(
                sorted(
                    {
                        item.source.absolute
                        for item in invocations
                        if item.source is not None
                        and not Path(item.source.absolute).is_file()
                    }
                )
            ),
        )

    def parse_output(
        self, configuration: BuildConfiguration, raw_output: str
    ) -> tuple[
        tuple[RawBuildCommand, ...],
        tuple[CompilerInvocation, ...],
        tuple[CompilationUnit, ...],
        tuple[Diagnostic, ...],
    ]:
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
                    diagnostic = _build_parse_diagnostic(
                        stripped, "Make directory stack underflow"
                    )
                    diagnostics.append(diagnostic)
                continue
            if _is_make_message(stripped):
                continue

            effective_directory = directory_stack[-1]
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
                            classification="unparsed",
                            parse_diagnostic=diagnostic,
                        )
                    )
                    continue
                if _is_cd(tokens):
                    target = Path(tokens[1])
                    if not target.is_absolute():
                        target = effective_directory / target
                    effective_directory = target.resolve()
                    commands.append(
                        RawBuildCommand(
                            raw_content=raw_segment,
                            working_directory=str(directory_stack[-1]),
                            classification="directory_change",
                        )
                    )
                    continue
                parsed = self._compiler_parser.parse(
                    raw_segment,
                    str(effective_directory),
                    configuration.repository_root,
                    configuration.id,
                    configuration.repository_id,
                )
                if parsed is not None:
                    commands.append(
                        RawBuildCommand(
                            raw_content=raw_segment,
                            working_directory=str(effective_directory),
                            classification="compiler",
                        )
                    )
                    for invocation in parsed:
                        invocations.append(invocation)
                        diagnostics.extend(invocation.parse_diagnostics)
                        for forced_include in invocation.arguments.forced_includes:
                            if not Path(forced_include.absolute).is_file():
                                diagnostics.append(
                                    Diagnostic(
                                        code="CI-BUILD-005",
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
                            continue
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
                                    code="CI-BUILD-004",
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
                    continue
                classification = (
                    "recursive_make" if _is_recursive_make(tokens) else "other"
                )
                commands.append(
                    RawBuildCommand(
                        raw_content=raw_segment,
                        working_directory=str(effective_directory),
                        classification=classification,
                    )
                )
        return (
            tuple(commands),
            tuple({item.id: item for item in invocations}.values()),
            tuple({item.id: item for item in units}.values()),
            tuple(diagnostics),
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
        code="CI-BUILD-003",
        severity=DiagnosticSeverity.WARNING,
        message="A Make dry-run command could not be parsed safely.",
        technical_details=f"{detail}: {raw}",
        missing_capability="complete_command_discovery",
        recoverability=Recoverability.REDUCED_CAPABILITY,
        suggested_actions=("Inspect the preserved raw Make output.",),
    )
