from typing import Protocol

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CallEdge,
    CompilationUnit,
    GeneratedReportMetadata,
    GlobalUsageEdge,
    IncludeEdge,
    InputArtifact,
    Repository,
    RepositoryFile,
    SourceAnalysisResult,
    SymbolOccurrence,
    WorkflowState,
)


class AnalysisStorage(Protocol):
    def initialize(self) -> None: ...

    def close(self) -> None: ...

    def save_repository(self, repository: Repository) -> None: ...

    def get_repository(self, repository_id: str) -> Repository | None: ...

    def list_repository_files(self, repository_id: str) -> tuple[RepositoryFile, ...]: ...

    def replace_repository_files(
        self, repository_id: str, files: tuple[RepositoryFile, ...]
    ) -> None: ...

    def save_diagnostics(
        self,
        repository_id: str,
        diagnostics: tuple[Diagnostic, ...],
        context: str = "general",
    ) -> None: ...

    def save_capabilities(
        self, repository_id: str, capabilities: tuple[AnalysisCapability, ...]
    ) -> None: ...

    def list_capabilities(
        self, repository_id: str
    ) -> tuple[AnalysisCapability, ...]: ...

    def schema_version(self) -> int: ...

    def save_report_metadata(self, report: GeneratedReportMetadata) -> None: ...

    def save_build_discovery(self, result: BuildDiscoveryResult) -> None: ...

    def get_cached_build_discovery(
        self, input_fingerprint: str
    ) -> BuildDiscoveryResult | None: ...

    def list_build_configurations(
        self, repository_id: str
    ) -> tuple[BuildConfiguration, ...]: ...

    def list_compilation_units(
        self, repository_id: str, build_configuration_name: str | None = None
    ) -> tuple[CompilationUnit, ...]: ...

    def list_diagnostics(
        self, repository_id: str, context_prefix: str | None = None
    ) -> tuple[Diagnostic, ...]: ...

    def save_input_artifact(self, artifact: InputArtifact) -> None: ...

    def list_input_artifacts(self, repository_id: str) -> tuple[InputArtifact, ...]: ...

    def save_workflow_state(self, state: WorkflowState) -> None: ...

    def list_workflow_states(self, repository_id: str) -> tuple[WorkflowState, ...]: ...

    def replace_source_analysis(self, result: SourceAnalysisResult) -> None: ...

    def list_source_analyses(self, repository_id: str) -> tuple[SourceAnalysisResult, ...]: ...

    def list_source_analyses_for_file(
        self, repository_file_id: str
    ) -> tuple[SourceAnalysisResult, ...]: ...

    def get_source_analysis_for_compilation_unit(
        self, compilation_unit_id: str
    ) -> SourceAnalysisResult | None: ...

    def find_symbols(
        self,
        repository_id: str,
        *,
        kind: str | None = None,
        name: str | None = None,
    ) -> tuple[SymbolOccurrence, ...]: ...

    def get_symbols_by_ids(
        self, repository_id: str, symbol_ids: tuple[str, ...]
    ) -> tuple[SymbolOccurrence, ...]: ...

    def find_call_edges(
        self,
        repository_id: str,
        *,
        caller_ids: tuple[str, ...] | None = None,
        callee_ids: tuple[str, ...] | None = None,
        callee_spelling: str | None = None,
    ) -> tuple[CallEdge, ...]: ...

    def find_include_edges(
        self, repository_id: str
    ) -> tuple[IncludeEdge, ...]: ...

    def find_global_usage_edges(
        self, repository_id: str
    ) -> tuple[GlobalUsageEdge, ...]: ...
