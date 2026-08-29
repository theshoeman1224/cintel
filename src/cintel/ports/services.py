"""Replaceable external behavior contracts for current and future phases."""

from typing import Any, Protocol

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    BuildConfiguration,
    BuildDiscoveryResult,
    CommandRequest,
    CommandInstruction,
    CompilationUnit,
    CompilerInvocation,
    ContextPackage,
    InputArtifactType,
    InputArtifact,
    RepositoryFile,
    RepositoryScan,
    SourceAnalysisResult,
)


class BuildDiscoveryProvider(Protocol):
    def discover(self, configuration: BuildConfiguration) -> BuildDiscoveryResult: ...

    def input_fingerprint(self, configuration: BuildConfiguration) -> str: ...

    def command_request(self, configuration: BuildConfiguration) -> CommandRequest: ...

    def discover_from_output(
        self,
        configuration: BuildConfiguration,
        raw_output: str,
        *,
        raw_error: str = "",
        exit_code: int = 0,
        artifact_hash: str | None = None,
    ) -> BuildDiscoveryResult: ...


class CompilerCommandParser(Protocol):
    def parse(
        self,
        raw_command: str,
        working_directory: str,
        repository_root: str,
        build_configuration_id: str,
    ) -> tuple[CompilerInvocation, ...] | None: ...


class CompilerMetadataProvider(Protocol):
    def version(self, executable: str, working_directory: str) -> str | None: ...


class CompilerProvider(Protocol):
    def probe(self, executable: str) -> dict[str, bool]: ...

    def enrich(self, invocation: CompilerInvocation) -> dict[str, Any]: ...


class SourceParser(Protocol):
    @property
    def parser_name(self) -> str: ...

    @property
    def parser_version(self) -> str: ...

    def analysis_fingerprint(
        self,
        repository_file: RepositoryFile,
        compilation_unit: CompilationUnit | None,
    ) -> str: ...

    def parse(
        self, repository_file: RepositoryFile, compilation_unit: CompilationUnit | None
    ) -> SourceAnalysisResult: ...


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
        self,
        repository_root: str,
        output_directory: str,
        diagnostics: tuple[Diagnostic, ...],
        build_configuration: BuildConfiguration | None = None,
    ) -> tuple[CommandInstruction, ...]: ...


class InputArtifactProvider(Protocol):
    def import_artifact(
        self,
        source_path: str,
        artifact_type: InputArtifactType,
        destination_directory: str,
        repository_id: str,
        repository_root: str,
        build_configuration_id: str | None = None,
        command_used: tuple[str, ...] | None = None,
        working_directory: str | None = None,
    ) -> InputArtifact: ...

    def refresh_staleness(self, artifact: InputArtifact) -> InputArtifact: ...

    def read_text(self, artifact: InputArtifact) -> str: ...


class AIProvider(Protocol):
    @property
    def enabled(self) -> bool: ...

    def generate(self, prompt: str, context: ContextPackage) -> str: ...
