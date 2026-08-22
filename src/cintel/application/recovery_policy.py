from __future__ import annotations

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    CapabilityStatus,
    InputArtifact,
    StalenessStatus,
    WorkflowStatus,
)


def missing_build_diagnostic(
    configuration: BuildConfiguration | None,
) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.BUILD_EVIDENCE_MISSING,
        severity=DiagnosticSeverity.WARNING,
        message="Build discovery evidence is not available yet.",
        technical_details="No persisted compilation units match the selected workflow.",
        missing_capability="compilation_units",
        recoverability=Recoverability.USER_ACTION,
        suggested_actions=("Capture or import a verbose GNU Make dry-run.",),
        related_paths=(
            (configuration.makefile,)
            if configuration and configuration.makefile
            else ()
        ),
    )


def invalid_artifact_diagnostic(artifact: InputArtifact) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.INPUT_ARTIFACT_INVALID,
        severity=DiagnosticSeverity.ERROR,
        message="The supplied input artifact failed validation.",
        technical_details=" ".join(artifact.validation_messages),
        missing_capability="validated_input_artifact",
        recoverability=Recoverability.USER_ACTION,
        suggested_actions=("Regenerate the input using the provided instructions.",),
        related_paths=(artifact.source, artifact.file_path),
    )


def stale_artifact_diagnostic(artifact: InputArtifact) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.INPUT_ARTIFACT_STALE,
        severity=DiagnosticSeverity.WARNING,
        message="A previously imported input artifact is stale.",
        technical_details="The preserved file no longer matches its recorded SHA-256 hash.",
        missing_capability="current_input_artifact",
        recoverability=Recoverability.USER_ACTION,
        suggested_actions=("Import a newly generated artifact and resume again.",),
        related_paths=(artifact.file_path,),
    )


def deduplicate_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    return tuple(
        {
            (item.code, item.message, item.related_paths): item
            for item in diagnostics
        }.values()
    )


def recovery_status(
    diagnostics: tuple[Diagnostic, ...],
    units_available: bool,
    artifacts: tuple[InputArtifact, ...] = (),
) -> WorkflowStatus:
    if any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics):
        return WorkflowStatus.INTERRUPTED
    if (
        diagnostics
        or not units_available
        or any(item.staleness_status is StalenessStatus.STALE for item in artifacts)
    ):
        return WorkflowStatus.REDUCED
    return WorkflowStatus.COMPLETED


def recovery_capabilities(units_available: bool) -> tuple[AnalysisCapability, ...]:
    return (
        AnalysisCapability(
            name="input_artifact_recovery",
            status=CapabilityStatus.AVAILABLE,
            reason="Input artifacts are validated, hashed, persisted, and checked for staleness.",
        ),
        AnalysisCapability(
            name="build_aware_analysis",
            status=(
                CapabilityStatus.AVAILABLE
                if units_available
                else CapabilityStatus.UNAVAILABLE
            ),
            reason=(
                "Compilation units are available."
                if units_available
                else "Repository scanning remains available without compilation units."
            ),
        ),
    )
