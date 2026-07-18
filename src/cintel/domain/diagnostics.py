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

