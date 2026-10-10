"""Replaceable external behavior contracts for current and future phases.

Application services depend on these protocols, never on the adapters that
implement them. New build systems, compilers, parsers, renderers, and AI
providers plug in here; the deterministic core must keep working with the
disabled or absent implementations.
"""

from typing import Any, Protocol

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    BuildConfiguration,
    BuildDiscoveryResult,
    CommandInstruction,
    CommandRequest,
    CompilationUnit,
    CompilerInvocation,
    ContextPackage,
    InputArtifact,
    InputArtifactType,
    RepositoryFile,
    RepositoryScan,
    SourceAnalysisResult,
)


class BuildDiscoveryProvider(Protocol):
    """Discover build membership and compiler invocations for one build."""

    def discover(self, configuration: BuildConfiguration) -> BuildDiscoveryResult:
        """Evaluate the configuration and return units, commands, and diagnostics."""
        ...

    def input_fingerprint(self, configuration: BuildConfiguration) -> str:
        """Fingerprint of the selection inputs; the cache key for discover."""
        ...

    def command_request(self, configuration: BuildConfiguration) -> CommandRequest:
        """The exact command discover would run, without running it."""
        ...

    def discover_from_output(
        self,
        configuration: BuildConfiguration,
        raw_output: str,
        *,
        raw_error: str = "",
        exit_code: int = 0,
        artifact_hash: str | None = None,
    ) -> BuildDiscoveryResult:
        """Parse captured output as if discover had run it."""
        ...


class CompilerCommandParser(Protocol):
    """Normalize raw shell commands into compiler invocations."""

    def parse(
        self,
        raw_command: str,
        working_directory: str,
        repository_root: str,
        build_configuration_id: str,
    ) -> tuple[CompilerInvocation, ...] | None:
        """Return invocations, or None when the command is not a compiler."""
        ...


class CompilerMetadataProvider(Protocol):
    """Read-only compiler identity lookup."""

    def version(self, executable: str, working_directory: str) -> str | None:
        """Return the compiler version string, or None when the probe fails."""
        ...


class CompilerProvider(Protocol):
    """Optional compiler enrichment; deterministic analysis must not need it."""

    def probe(self, executable: str) -> dict[str, bool]:
        """Report which optional compiler capabilities are available."""
        ...

    def enrich(self, invocation: CompilerInvocation) -> dict[str, Any]:
        """Return additional evidence for one invocation."""
        ...


class SourceParser(Protocol):
    """Conservative source extraction behind a stable parser identity."""

    @property
    def parser_name(self) -> str:
        """Identifier stored with every result."""
        ...

    @property
    def parser_version(self) -> str:
        """Version stored with every result; a bump invalidates reuse."""
        ...

    def analysis_fingerprint(
        self,
        repository_file: RepositoryFile,
        compilation_unit: CompilationUnit | None,
    ) -> str:
        """Cache key covering source hash, unit fingerprint, and parser version."""
        ...

    def parse(
        self, repository_file: RepositoryFile, compilation_unit: CompilationUnit | None
    ) -> SourceAnalysisResult:
        """Extract symbols, relationships, and diagnostics for one target."""
        ...


class RepositoryDiscoveryProvider(Protocol):
    """Inventory repository files for scanning."""

    def discover(
        self,
        repository_root: str,
        repository_id: str,
        exclusions: tuple[str, ...],
        previous_files: tuple[RepositoryFile, ...] = (),
    ) -> RepositoryScan:
        """Scan the tree, reusing hashes from previous_files when metadata matches."""
        ...


class ReportRenderer(Protocol):
    """Render one report family from typed report data."""

    def render(self, report_name: str, data: Any) -> str:
        """Render a supported family; raise ValueError for unknown names."""
        ...


class InputGuidanceProvider(Protocol):
    """Turn missing-capability diagnostics into exact capture instructions."""

    def instructions_for(
        self,
        repository_root: str,
        output_directory: str,
        diagnostics: tuple[Diagnostic, ...],
        build_configuration: BuildConfiguration | None = None,
    ) -> tuple[CommandInstruction, ...]:
        """Build validated, non-executed commands for each missing input."""
        ...


class InputArtifactProvider(Protocol):
    """Import, validate, and re-read user-supplied evidence."""

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
    ) -> InputArtifact:
        """Copy evidence under the workspace and validate its structure."""
        ...

    def refresh_staleness(self, artifact: InputArtifact) -> InputArtifact:
        """Re-hash the preserved copy and source to classify staleness."""
        ...

    def read_text(self, artifact: InputArtifact) -> str:
        """Read the preserved artifact; raise InputArtifactError when unreadable."""
        ...


class AIProvider(Protocol):
    """Optional AI generation; disabled by default and never required."""

    @property
    def enabled(self) -> bool:
        """Whether this provider may be called."""
        ...

    def generate(self, prompt: str, context: ContextPackage) -> str:
        """Generate content from a context package; disabled adapters raise."""
        ...
