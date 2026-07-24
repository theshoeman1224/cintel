import unittest
from dataclasses import replace
from datetime import datetime, timezone

from cintel.application.recovery_policy import (
    deduplicate_diagnostics,
    invalid_artifact_diagnostic,
    recovery_status,
)
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import (
    ArtifactValidationStatus,
    InputArtifact,
    InputArtifactType,
    StalenessStatus,
    WorkflowStatus,
)


def artifact() -> InputArtifact:
    return InputArtifact(
        id="artifact-1",
        repository_id="repository-1",
        artifact_type=InputArtifactType.MAKE_DRY_RUN,
        file_path="/input/make.txt",
        source="/source/make.txt",
        command_used=("make", "-n"),
        working_directory="/repo",
        content_hash="a" * 64,
        creation_time=datetime.now(timezone.utc),
        validation_status=ArtifactValidationStatus.VALID,
        validation_messages=("valid",),
        build_configuration_id="build-1",
        staleness_status=StalenessStatus.CURRENT,
    )


class RecoveryPolicyTests(unittest.TestCase):
    def test_status_distinguishes_completed_reduced_and_interrupted(self) -> None:
        current = artifact()
        warning = Diagnostic(
            code="CI-INPUT-001",
            severity=DiagnosticSeverity.WARNING,
            message="missing",
        )
        invalid = replace(
            current,
            validation_status=ArtifactValidationStatus.INVALID,
            validation_messages=("empty",),
        )

        self.assertIs(WorkflowStatus.COMPLETED, recovery_status((), True, (current,)))
        self.assertIs(WorkflowStatus.REDUCED, recovery_status((), False, (current,)))
        self.assertIs(
            WorkflowStatus.REDUCED, recovery_status((warning,), True, (current,))
        )
        self.assertIs(
            WorkflowStatus.REDUCED,
            recovery_status(
                (), True, (replace(current, staleness_status=StalenessStatus.STALE),)
            ),
        )
        self.assertIs(
            WorkflowStatus.INTERRUPTED,
            recovery_status((invalid_artifact_diagnostic(invalid),), True, (invalid,)),
        )

    def test_diagnostic_deduplication_preserves_distinct_paths(self) -> None:
        first = Diagnostic(
            code="CI-BUILD-005",
            severity=DiagnosticSeverity.WARNING,
            message="missing include",
            related_paths=("one.h",),
        )
        second = replace(first, related_paths=("two.h",))
        self.assertEqual(
            (first, second), deduplicate_diagnostics((first, first, second))
        )


if __name__ == "__main__":
    unittest.main()
