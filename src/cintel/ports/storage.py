"""Persistence contract for all analysis state.

The application layer reads and writes everything through this protocol.
Rows are scoped by repository id; source-analysis rows are additionally
scoped by file or compilation unit so one file can be analyzed once per
build configuration.
"""

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
    """Durable state for one workspace database."""

    def initialize(self) -> None:
        """Create or migrate the database; raise StorageError when unusable."""
        ...

    def close(self) -> None:
        """Release the connection; safe to call more than once."""
        ...

    def save_repository(self, repository: Repository) -> None:
        """Insert or update the repository row."""
        ...

    def get_repository(self, repository_id: str) -> Repository | None:
        """Return the stored repository, or None when absent."""
        ...

    def list_repository_files(self, repository_id: str) -> tuple[RepositoryFile, ...]:
        """Files for a repository, ordered by relative path."""
        ...

    def replace_repository_files(
        self, repository_id: str, files: tuple[RepositoryFile, ...]
    ) -> None:
        """Upsert the inventory and delete rows no longer present."""
        ...

    def save_diagnostics(
        self,
        repository_id: str,
        diagnostics: tuple[Diagnostic, ...],
        context: str = "general",
    ) -> None:
        """Replace diagnostics for one context key, such as scan or parse:file:<id>."""
        ...

    def save_capabilities(
        self, repository_id: str, capabilities: tuple[AnalysisCapability, ...]
    ) -> None:
        """Replace all capability records for the repository."""
        ...

    def list_capabilities(
        self, repository_id: str
    ) -> tuple[AnalysisCapability, ...]:
        """Capabilities ordered by name."""
        ...

    def schema_version(self) -> int:
        """Stored schema version, 0 when uninitialized."""
        ...

    def save_report_metadata(self, report: GeneratedReportMetadata) -> None:
        """Insert or update one generated-report record."""
        ...

    def save_build_discovery(self, result: BuildDiscoveryResult) -> None:
        """Persist a run with its configuration, invocations, units, and commands."""
        ...

    def get_cached_build_discovery(
        self, input_fingerprint: str
    ) -> BuildDiscoveryResult | None:
        """Result whose input fingerprint matches, or None."""
        ...

    def list_build_configurations(
        self, repository_id: str
    ) -> tuple[BuildConfiguration, ...]:
        """Configurations ordered by name and id."""
        ...

    def list_compilation_units(
        self, repository_id: str, build_configuration_name: str | None = None
    ) -> tuple[CompilationUnit, ...]:
        """Units, optionally filtered by configuration name."""
        ...

    def list_diagnostics(
        self, repository_id: str, context_prefix: str | None = None
    ) -> tuple[Diagnostic, ...]:
        """Diagnostics in insertion order, optionally filtered by context prefix."""
        ...

    def save_input_artifact(self, artifact: InputArtifact) -> None:
        """Insert or update one imported-evidence record."""
        ...

    def list_input_artifacts(self, repository_id: str) -> tuple[InputArtifact, ...]:
        """Imported evidence ordered by id."""
        ...

    def save_workflow_state(self, state: WorkflowState) -> None:
        """Upsert the state of one workflow stage."""
        ...

    def list_workflow_states(self, repository_id: str) -> tuple[WorkflowState, ...]:
        """States ordered by update time and stage."""
        ...

    def replace_source_analysis(self, result: SourceAnalysisResult) -> None:
        """Replace one run with its symbols, relationships, and diagnostics."""
        ...

    def list_source_analyses(self, repository_id: str) -> tuple[SourceAnalysisResult, ...]:
        """All stored runs for a repository."""
        ...

    def list_source_analyses_for_file(
        self, repository_file_id: str
    ) -> tuple[SourceAnalysisResult, ...]:
        """Runs for one file; unit-scoped runs first, then a deterministic order."""
        ...

    def get_source_analysis_for_compilation_unit(
        self, compilation_unit_id: str
    ) -> SourceAnalysisResult | None:
        """Run stored for a unit, or None when absent."""
        ...

    def find_symbols(
        self,
        repository_id: str,
        *,
        kind: str | None = None,
        name: str | None = None,
    ) -> tuple[SymbolOccurrence, ...]:
        """Symbol occurrences with optional kind and exact-name filters."""
        ...

    def get_symbols_by_ids(
        self, repository_id: str, symbol_ids: tuple[str, ...]
    ) -> tuple[SymbolOccurrence, ...]:
        """Occurrences for the given symbol ids; empty input returns ()."""
        ...

    def find_call_edges(
        self,
        repository_id: str,
        *,
        caller_ids: tuple[str, ...] | None = None,
        callee_ids: tuple[str, ...] | None = None,
        callee_spelling: str | None = None,
    ) -> tuple[CallEdge, ...]:
        """Call edges with optional filters; an empty id filter returns ()."""
        ...

    def find_include_edges(
        self, repository_id: str
    ) -> tuple[IncludeEdge, ...]:
        """All include edges for a repository."""
        ...

    def find_global_usage_edges(
        self, repository_id: str
    ) -> tuple[GlobalUsageEdge, ...]:
        """All global-usage edges for a repository."""
        ...
