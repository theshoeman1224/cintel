"""Replaceable external behavior contracts for current and future phases."""

from typing import Any, Protocol

from cintel.domain.models import (
    AnalysisResult,
    BuildConfiguration,
    CommandInstruction,
    CompilationUnit,
    CompilerInvocation,
    ContextPackage,
    RepositoryFile,
)


class BuildDiscoveryProvider(Protocol):
    def discover(
        self, configuration: BuildConfiguration
    ) -> tuple[CompilationUnit, ...]: ...


class CompilerProvider(Protocol):
    def probe(self, executable: str) -> dict[str, bool]: ...

    def enrich(self, invocation: CompilerInvocation) -> dict[str, Any]: ...


class SourceParser(Protocol):
    def parse(
        self, repository_file: RepositoryFile, compilation_unit: CompilationUnit | None
    ) -> AnalysisResult: ...


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

