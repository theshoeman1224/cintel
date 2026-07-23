"""Replaceable external behavior contracts for current and future phases."""

from typing import Any, Protocol

from cintel.domain.models import (
    AnalysisResult,
    BuildConfiguration,
    BuildDiscoveryResult,
    CommandRequest,
    CommandInstruction,
    CompilationUnit,
    CompilerInvocation,
    ContextPackage,
    RepositoryFile,
    RepositoryScan,
)


class BuildDiscoveryProvider(Protocol):
    def discover(self, configuration: BuildConfiguration) -> BuildDiscoveryResult: ...

    def input_fingerprint(self, configuration: BuildConfiguration) -> str: ...

    def command_request(self, configuration: BuildConfiguration) -> CommandRequest: ...


class CompilerCommandParser(Protocol):
    def parse(
        self,
        raw_command: str,
        working_directory: str,
        repository_root: str,
        build_configuration_id: str,
        repository_id: str,
    ) -> tuple[CompilerInvocation, ...] | None: ...


class CompilerMetadataProvider(Protocol):
    def version(self, executable: str, working_directory: str) -> str | None: ...


class CompilerProvider(Protocol):
    def probe(self, executable: str) -> dict[str, bool]: ...

    def enrich(self, invocation: CompilerInvocation) -> dict[str, Any]: ...


class SourceParser(Protocol):
    def parse(
        self, repository_file: RepositoryFile, compilation_unit: CompilationUnit | None
    ) -> AnalysisResult: ...


class RepositoryDiscoveryProvider(Protocol):
    def discover(
        self,
        repository_root: str,
        repository_id: str,
        exclusions: tuple[str, ...],
        previous_files: tuple[RepositoryFile, ...] = (),
    ) -> RepositoryScan: ...


class ReportRenderer(Protocol):
    def render(self, report_name: str, data: Any) -> str: ...


class InputGuidanceProvider(Protocol):
    def instructions_for(
        self, missing_capabilities: tuple[str, ...]
    ) -> tuple[CommandInstruction, ...]: ...


class AIProvider(Protocol):
    @property
    def enabled(self) -> bool: ...

    def generate(self, prompt: str, context: ContextPackage) -> str: ...
