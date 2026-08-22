"""Structured diagnostics shared by all layers."""

from dataclasses import dataclass, field
from enum import StrEnum


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Recoverability(StrEnum):
    AUTOMATIC = "automatic"
    USER_ACTION = "user_action"
    REDUCED_CAPABILITY = "reduced_capability"
    NOT_RECOVERABLE = "not_recoverable"


class DiagnosticCode(StrEnum):
    REPOSITORY_ROOT_UNAVAILABLE = "CI-REPO-001"
    DIRECTORY_UNREADABLE = "CI-REPO-002"
    SOURCE_SYMLINK_SKIPPED = "CI-REPO-003"
    FILE_UNREADABLE = "CI-REPO-004"
    MAKE_NOT_EXECUTABLE = "CI-BUILD-001"
    MAKE_DRY_RUN_INCOMPLETE = "CI-BUILD-002"
    COMMAND_UNPARSEABLE = "CI-BUILD-003"
    MISSING_SOURCE_FILE = "CI-BUILD-004"
    MISSING_FORCED_INCLUDE = "CI-BUILD-005"
    NO_COMPILER_RECOGNIZED = "CI-COMP-001"
    COMPILER_OPTION_MISSING_VALUE = "CI-COMP-002"
    BUILD_EVIDENCE_MISSING = "CI-INPUT-001"
    INPUT_ARTIFACT_INVALID = "CI-INPUT-002"
    INPUT_ARTIFACT_STALE = "CI-INPUT-003"
    CONSERVATIVE_PARSE_LIMITATION = "CI-PARSE-001"


@dataclass(frozen=True, slots=True)
class RelatedCommand:
    arguments: tuple[str, ...]
    working_directory: str


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    technical_details: str = ""
    missing_capability: str | None = None
    recoverability: Recoverability = Recoverability.AUTOMATIC
    suggested_actions: tuple[str, ...] = ()
    related_paths: tuple[str, ...] = ()
    related_commands: tuple[RelatedCommand, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        parts = self.code.split("-")
        if len(parts) != 3 or parts[0] != "CI" or not parts[2].isdigit():
            raise ValueError(f"Invalid diagnostic code: {self.code}")

