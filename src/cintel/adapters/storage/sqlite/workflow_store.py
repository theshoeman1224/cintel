"""Workflow state, input artifacts, and generated-report metadata."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from cintel.adapters.storage.serialization import (
    input_artifact_from_dict,
    json_default,
)
from cintel.adapters.storage.sqlite.base import StoreBase
from cintel.domain.models import (
    GeneratedReportMetadata,
    InputArtifact,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)


class WorkflowStore(StoreBase):

    def save_report_metadata(self, report: GeneratedReportMetadata) -> None:
        self._connect().execute(
            """
            INSERT INTO generated_reports
              (id, repository_id, report_name, format, file_path,
               content_sha256, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              file_path=excluded.file_path,
              content_sha256=excluded.content_sha256,
              generated_at=excluded.generated_at
            """,
            (
                report.id,
                report.repository_id,
                report.report_name,
                report.format,
                report.file_path,
                report.content_sha256,
                report.generated_at.isoformat(),
            ),
        )
        self._connect().commit()

    def save_input_artifact(self, artifact: InputArtifact) -> None:
        self._connect().execute(
            """
            INSERT INTO input_artifacts
              (id, repository_id, artifact_type, file_path, content_hash,
               validation_status, staleness_status, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              file_path=excluded.file_path,
              validation_status=excluded.validation_status,
              staleness_status=excluded.staleness_status,
              payload=excluded.payload
            """,
            (
                artifact.id,
                artifact.repository_id,
                artifact.artifact_type.value,
                artifact.file_path,
                artifact.content_hash,
                artifact.validation_status.value,
                artifact.staleness_status.value,
                json.dumps(asdict(artifact), default=json_default, sort_keys=True),
            ),
        )
        self._connect().commit()

    def list_input_artifacts(self, repository_id: str) -> tuple[InputArtifact, ...]:
        rows = self._connect().execute(
            "SELECT payload FROM input_artifacts WHERE repository_id = ? ORDER BY id",
            (repository_id,),
        ).fetchall()
        return tuple(input_artifact_from_dict(json.loads(row[0])) for row in rows)

    def save_workflow_state(self, state: WorkflowState) -> None:
        self._connect().execute(
            """
            INSERT INTO workflow_state (repository_id, stage, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repository_id, stage) DO UPDATE SET
              status=excluded.status,
              updated_at=excluded.updated_at,
              payload=excluded.payload
            """,
            (
                state.repository_id,
                state.stage,
                state.status.value,
                state.updated_at.isoformat(),
                json.dumps(dict(state.details), sort_keys=True),
            ),
        )
        self._connect().commit()

    def list_workflow_states(self, repository_id: str) -> tuple[WorkflowState, ...]:
        rows = self._connect().execute(
            """
            SELECT repository_id, stage, status, updated_at, payload
            FROM workflow_state WHERE repository_id = ? ORDER BY updated_at, stage
            """,
            (repository_id,),
        ).fetchall()
        return tuple(
            WorkflowState(
                repository_id=row[0],
                stage=WorkflowStage(row[1]),
                status=WorkflowStatus(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                details=tuple(sorted(json.loads(row[4]).items())),
            )
            for row in rows
        )
