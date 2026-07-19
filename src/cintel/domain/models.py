"""Pure domain models.

The domain intentionally contains no process, database, build-system, compiler,
CLI, or AI SDK dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cintel.domain.diagnostics import Diagnostic


class FileKind(StrEnum):
    C_SOURCE = "c_source"
    C_HEADER = "c_header"
    MAKEFILE = "makefile"
    MAKE_FRAGMENT = "make_fragment"
    OTHER = "other"


class SymbolKind(StrEnum):
    FUNCTION = "function"
    VARIABLE = "variable"
    TYPE = "type"
    MACRO = "macro"


class Linkage(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class RelationshipResolution(StrEnum):
    CONFIRMED_DIRECT = "confirmed_direct"
    POSSIBLE_INDIRECT = "possible_indirect"
    UNRESOLVED = "unresolved"


class EvidenceKind(StrEnum):
    EXTRACTED_FACT = "extracted_fact"
    CALCULATED_METRIC = "calculated_metric"
    HEURISTIC_RESULT = "heuristic_result"
    INFERRED_RELATIONSHIP = "inferred_relationship"
    UNAVAILABLE_INFORMATION = "unavailable_information"


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ArtifactValidationStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class StalenessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class CommandRisk(StrEnum):
    READ_ONLY = "read_only"
    MAKEFILE_EVALUATION = "makefile_evaluation"
    MUTATING = "mutating"


class OutputDestination(StrEnum):
    CAPTURE = "capture"
    FILE = "file"
    INHERIT = "inherit"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    path: str
    line: int
    column: int = 1
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class PathReference:
    original: str
    absolute: str
    repository_relative: str | None = None


@dataclass(frozen=True, slots=True)
class Repository:
    id: str
    root: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    id: str
    repository_id: str
    relative_path: str
    absolute_path: str
    kind: FileKind
    size: int
    modified_at: datetime
    content_sha256: str


@dataclass(frozen=True, slots=True)
class RepositoryScan:
    repository: Repository
    files: tuple[RepositoryFile, ...]
    diagnostics: tuple[Diagnostic, ...]
    capabilities: tuple[AnalysisCapability, ...]
    scanned_at: datetime
    hashes_computed: int
    hashes_reused: int


@dataclass(frozen=True, slots=True)
class GeneratedReportMetadata:
    id: str
    repository_id: str
    report_name: str
    format: str
    file_path: str
    content_sha256: str
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class BuildConfiguration:
    id: str
    repository_id: str
    name: str
    makefile: str | None = None
    working_directory: str | None = None
    target: str | None = None
    make_variables: tuple[tuple[str, str], ...] = ()
    environment_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class IncludePath:
    path: PathReference
    is_system: bool = False


@dataclass(frozen=True, slots=True)
class MacroDefinition:
    name: str
    value: str | None = None


@dataclass(frozen=True, slots=True)
class CompilerArgumentSet:
    include_paths: tuple[IncludePath, ...] = ()
    defines: tuple[MacroDefinition, ...] = ()
    undefines: tuple[str, ...] = ()
    forced_includes: tuple[PathReference, ...] = ()
    language_standard: str | None = None
    optimization_flags: tuple[str, ...] = ()
    debug_flags: tuple[str, ...] = ()
    warning_flags: tuple[str, ...] = ()
    architecture_flags: tuple[str, ...] = ()
    dependency_flags: tuple[str, ...] = ()
    unclassified_arguments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompilerInvocation:
    id: str
    compiler_executable: str
    launchers: tuple[str, ...]
    source: PathReference | None
    object_file: PathReference | None
    working_directory: str
    raw_command: str
    raw_arguments: tuple[str, ...]
    arguments: CompilerArgumentSet
    parse_diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class CompilationUnit:
    id: str
    repository_id: str
    build_configuration_id: str
    source_file_id: str | None
    compiler_invocation: CompilerInvocation
    fingerprint: str


@dataclass(frozen=True, slots=True)
class FunctionSymbol:
    id: str
    name: str
    location: SourceLocation
    is_definition: bool
    linkage: Linkage
    return_type: str | None = None
    parameters: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class VariableSymbol:
    id: str
    name: str
    location: SourceLocation
    type_spelling: str | None
    linkage: Linkage
    is_definition: bool
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class TypeSymbol:
    id: str
    name: str
    type_kind: str
    location: SourceLocation
    is_definition: bool
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class MacroSymbol:
    id: str
    name: str
    location: SourceLocation
    replacement: str | None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    kind: EvidenceKind
    description: str
    location: SourceLocation | None = None
    provenance: str | None = None


@dataclass(frozen=True, slots=True)
class IncludeRelationship:
    id: str
    source_file_id: str
    included_spelling: str
    resolved_file_id: str | None
    evidence: tuple[RelationshipEvidence, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class CallRelationship:
    id: str
    caller_id: str
    callee_id: str | None
    callee_spelling: str
    resolution: RelationshipResolution
    evidence: tuple[RelationshipEvidence, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class GlobalUsageRelationship:
    id: str
    function_id: str
    variable_id: str | None
    variable_spelling: str
    evidence: tuple[RelationshipEvidence, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class AnalysisCapability:
    name: str
    status: CapabilityStatus
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    repository_id: str
    capabilities: tuple[AnalysisCapability, ...]
    diagnostics: tuple[Diagnostic, ...]
    completed_stages: tuple[str, ...]
    interrupted_stage: str | None = None


@dataclass(frozen=True, slots=True)
class InputArtifact:
    id: str
    artifact_type: str
    file_path: str
    source: str
    command_used: tuple[str, ...] | None
    working_directory: str | None
    content_hash: str
    creation_time: datetime
    validation_status: ArtifactValidationStatus
    validation_messages: tuple[str, ...]
    build_configuration_id: str | None
    staleness_status: StalenessStatus


@dataclass(frozen=True, slots=True)
class CommandInstruction:
    title: str
    reason: str
    arguments: tuple[str, ...]
    working_directory: str
    expected_output_file: str | None
    risk: CommandRisk
    validation_steps: tuple[str, ...]
    resume_command: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextPackage:
    function_id: str
    title: str
    sections: tuple[tuple[str, str], ...]
    character_budget: int
    used_characters: int
    capabilities: tuple[AnalysisCapability, ...]
    evidence: tuple[RelationshipEvidence, ...]


@dataclass(frozen=True, slots=True)
class CommandRequest:
    arguments: tuple[str, ...]
    working_directory: str
    environment_overrides: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 30.0
    output_destination: OutputDestination = OutputDestination.CAPTURE
    output_file: str | None = None
    risk: CommandRisk = CommandRisk.READ_ONLY

    def __post_init__(self) -> None:
        if not self.arguments:
            raise ValueError("Command arguments must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Command timeout must be positive")
        if self.output_destination is OutputDestination.FILE and not self.output_file:
            raise ValueError("A file output destination requires output_file")


@dataclass(frozen=True, slots=True)
class CommandResult:
    standard_output: str
    standard_error: str
    exit_code: int
    duration_seconds: float
    executed_command: tuple[str, ...]
    effective_working_directory: str
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ToolStatus:
    name: str
    path: str | None
    version: str | None
    available: bool
    details: str = ""


@dataclass(frozen=True, slots=True)
class DoctorReport:
    repository_root: str
    python_version: str
    tools: tuple[ToolStatus, ...]
    output_directory_writable: bool
    detected_inputs: dict[str, tuple[str, ...]]
    capabilities: tuple[AnalysisCapability, ...]
    diagnostics: tuple[Diagnostic, ...]
    recommended_actions: tuple[str, ...]


JsonValue = str | int | float | bool | None | list[Any] | dict[str, Any]
