"""Pure domain models, diagnostics, and errors."""

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    Recoverability,
    RelatedCommand,
)

__all__ = ["Diagnostic", "DiagnosticSeverity", "Recoverability", "RelatedCommand"]

