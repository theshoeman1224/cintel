from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from cintel.application.build_discovery import BuildDiscoveryService
from cintel.application.recovery_policy import (
    deduplicate_diagnostics,
    invalid_artifact_diagnostic,
    missing_build_diagnostic,
    recovery_capabilities,
    recovery_status,
    stale_artifact_diagnostic,
)
from cintel.application.scanning import RepositoryScanService
from cintel.application.storage_session import storage_session
from cintel.configuration.models import AppConfig
from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import (
    ArtifactValidationStatus,
    BuildConfiguration,
    BuildDiscoveryResult,
    CompilationUnit,
    GeneratedReportMetadata,
    InputArtifact,
    InputArtifactType,
    RecoveryResult,
    StalenessStatus,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from cintel.ports.artifacts import ArtifactWriter
from cintel.ports.services import InputArtifactProvider, InputGuidanceProvider, ReportRenderer
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.hashing import stable_id
from cintel.utilities.paths import stable_repository_id
from cintel.utilities.secrets import redact_assignment_arguments


class GuidedRecoveryService:
    def __init__(
        self,
        scanner: RepositoryScanService,
        build_discovery: BuildDiscoveryService,
        artifact_provider: InputArtifactProvider,
        guidance_provider: InputGuidanceProvider,
        guidance_renderer: ReportRenderer,
        artifact_writer: ArtifactWriter,
        storage_factory: Callable[[Path], AnalysisStorage],
    ) -> None:
        self._scanner = scanner
        self._build_discovery = build_discovery
        self._artifact_provider = artifact_provider
        self._guidance_provider = guidance_provider
        self._guidance_renderer = guidance_renderer
        self._artifact_writer = artifact_writer
        self._storage_factory = storage_factory

    def setup(
        self, app_config: AppConfig, configuration: BuildConfiguration | None
    ) -> RecoveryResult:
        scan = self._scanner.scan(app_config).scan
        with self._storage(app_config) as storage:
            units, diagnostics, artifacts = self._stored_evidence(
                storage, scan.repository.id, configuration
            )
            storage.save_diagnostics(scan.repository.id, diagnostics, "recovery:setup")
            self._save_state(
                storage,
                scan.repository.id,
                WorkflowStage.REPOSITORY_SCAN,
                WorkflowStatus.COMPLETED,
            )
            setup_status = (
                recovery_status(diagnostics, True, artifacts)
                if units
                else WorkflowStatus.PENDING
            )
            self._save_state(storage, scan.repository.id, WorkflowStage.GUIDED_RECOVERY, setup_status)
        return self._result(
            app_config,
            configuration,
            artifacts,
            diagnostics,
            units_available=bool(units),
        )

    def instructions(
        self, app_config: AppConfig, configuration: BuildConfiguration | None
    ) -> RecoveryResult:
        scan = self._scanner.scan(app_config).scan
        with self._storage(app_config) as storage:
            units, diagnostics, artifacts = self._stored_evidence(
                storage, scan.repository.id, configuration
            )
        return self._result(
            app_config,
            configuration,
            artifacts,
            diagnostics,
            units_available=bool(units),
        )

    def resume(
        self,
        app_config: AppConfig,
        configuration: BuildConfiguration | None,
        input_file: Path | None = None,
        artifact_type: InputArtifactType = InputArtifactType.MAKE_DRY_RUN,
    ) -> RecoveryResult:
        scan = self._scanner.scan(app_config).scan
        repository_id = scan.repository.id
        build_result: BuildDiscoveryResult | None = None
        diagnostics: list[Diagnostic] = []
        with self._storage(app_config) as storage:
            if input_file is not None:
                build_result, import_diagnostics = self._import_input(
                    app_config,
                    configuration,
                    input_file,
                    artifact_type,
                    repository_id,
                    storage,
                )
                diagnostics.extend(import_diagnostics)

            artifacts, stale_diagnostics = self._refresh_artifacts(
                storage, repository_id, configuration
            )
            diagnostics.extend(stale_diagnostics)
            units = storage.list_compilation_units(
                repository_id, configuration.name if configuration else None
            )
            diagnostics = list(
                deduplicate_diagnostics(
                    (*diagnostics, *storage.list_diagnostics(repository_id, "build:"))
                )
            )
            if not units and not diagnostics:
                diagnostics.append(missing_build_diagnostic(configuration))
            status = recovery_status(tuple(diagnostics), bool(units), artifacts)
            storage.save_diagnostics(repository_id, tuple(diagnostics), "recovery:resume")
            self._save_state(storage, repository_id, WorkflowStage.INPUT_VALIDATION, status)
            self._save_state(storage, repository_id, WorkflowStage.GUIDED_RECOVERY, status)
            if units:
                self._save_state(
                    storage,
                    repository_id,
                    WorkflowStage.BUILD_DISCOVERY,
                    WorkflowStatus.COMPLETED,
                )
        return self._result(
            app_config,
            configuration,
            artifacts,
            tuple(diagnostics),
            units_available=bool(units),
            forced_status=status,
            build_result=build_result,
        )

    def _result(
        self,
        app_config: AppConfig,
        configuration: BuildConfiguration | None,
        artifacts: tuple[InputArtifact, ...],
        diagnostics: tuple[Diagnostic, ...],
        *,
        units_available: bool,
        forced_status: WorkflowStatus | None = None,
        build_result: BuildDiscoveryResult | None = None,
    ) -> RecoveryResult:
        instructions = (
            ()
            if units_available and not diagnostics
            else self._guidance_provider.instructions_for(
                app_config.repository_root,
                app_config.output_directory,
                diagnostics,
                configuration,
            )
        )
        report_path = Path(app_config.output_directory) / "REQUIRED_INPUTS.md"
        content = self._guidance_renderer.render("required_inputs", instructions)
        self._artifact_writer.write_text(report_path, content)
        repository_id = stable_repository_id(app_config.repository_root)
        with self._storage(app_config) as storage:
            storage.save_report_metadata(
                GeneratedReportMetadata(
                    id=stable_id("report", repository_id, "required_inputs", "markdown"),
                    repository_id=repository_id,
                    report_name="required_inputs",
                    format="markdown",
                    file_path=str(report_path),
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                    generated_at=datetime.now(timezone.utc),
                )
            )
            states = storage.list_workflow_states(repository_id)
        status = forced_status or recovery_status(diagnostics, units_available, artifacts)
        return RecoveryResult(
            repository_id=repository_id,
            status=status,
            artifacts=artifacts,
            diagnostics=diagnostics,
            instructions=instructions,
            capabilities=recovery_capabilities(units_available),
            completed_stages=tuple(
                state.stage for state in states if state.status is WorkflowStatus.COMPLETED
            ),
            interrupted_stage=(
                WorkflowStage.INPUT_VALIDATION
                if status is WorkflowStatus.INTERRUPTED
                else None
            ),
            required_inputs_report=str(report_path),
            build_result=build_result,
        )

    @contextmanager
    def _storage(self, app_config: AppConfig) -> Iterator[AnalysisStorage]:
        with storage_session(self._storage_factory, app_config.database_path) as storage:
            yield storage

    @staticmethod
    def _stored_evidence(
        storage: AnalysisStorage,
        repository_id: str,
        configuration: BuildConfiguration | None,
    ) -> tuple[
        tuple[CompilationUnit, ...],
        tuple[Diagnostic, ...],
        tuple[InputArtifact, ...],
    ]:
        units = storage.list_compilation_units(
            repository_id, configuration.name if configuration else None
        )
        diagnostics = deduplicate_diagnostics(
            storage.list_diagnostics(repository_id, "build:")
        )
        if not units and not diagnostics:
            diagnostics = (missing_build_diagnostic(configuration),)
        return units, diagnostics, storage.list_input_artifacts(repository_id)

    def _import_input(
        self,
        app_config: AppConfig,
        configuration: BuildConfiguration | None,
        input_file: Path,
        artifact_type: InputArtifactType,
        repository_id: str,
        storage: AnalysisStorage,
    ) -> tuple[BuildDiscoveryResult | None, tuple[Diagnostic, ...]]:
        command_used = (
            redact_assignment_arguments(self._build_discovery.preview(configuration))
            if configuration and artifact_type is InputArtifactType.MAKE_DRY_RUN
            else None
        )
        artifact = self._artifact_provider.import_artifact(
            str(input_file),
            artifact_type,
            str(Path(app_config.output_directory) / "input"),
            repository_id,
            app_config.repository_root,
            configuration.id if configuration else None,
            command_used,
            configuration.working_directory
            if configuration and configuration.working_directory
            else app_config.repository_root,
        )
        storage.save_input_artifact(artifact)
        if artifact.validation_status is ArtifactValidationStatus.INVALID:
            return None, (invalid_artifact_diagnostic(artifact),)
        if artifact_type is not InputArtifactType.MAKE_DRY_RUN:
            return None, ()
        if configuration is None:
            return None, (missing_build_diagnostic(None),)
        raw_output = self._artifact_provider.read_text(artifact).replace(
            "<FIXTURE_ROOT>", app_config.repository_root
        )
        result = self._build_discovery.discover_saved(
            app_config, configuration, raw_output, artifact.content_hash
        )
        return result, result.diagnostics

    def _refresh_artifacts(
        self,
        storage: AnalysisStorage,
        repository_id: str,
        configuration: BuildConfiguration | None,
    ) -> tuple[tuple[InputArtifact, ...], tuple[Diagnostic, ...]]:
        artifacts: list[InputArtifact] = []
        diagnostics: list[Diagnostic] = []
        for artifact in storage.list_input_artifacts(repository_id):
            refreshed = self._artifact_provider.refresh_staleness(artifact)
            if (
                configuration is not None
                and refreshed.build_configuration_id is not None
                and refreshed.build_configuration_id != configuration.id
            ):
                refreshed = replace(
                    refreshed,
                    staleness_status=StalenessStatus.STALE,
                    validation_messages=refreshed.validation_messages
                    + ("Artifact belongs to a different build configuration.",),
                )
            if refreshed != artifact:
                storage.save_input_artifact(refreshed)
            artifacts.append(refreshed)
            if refreshed.staleness_status is StalenessStatus.STALE:
                diagnostics.append(stale_artifact_diagnostic(refreshed))
        return tuple(artifacts), tuple(diagnostics)

    @staticmethod
    def _save_state(
        storage: AnalysisStorage, repository_id: str, stage: str, status: WorkflowStatus
    ) -> None:
        storage.save_workflow_state(
            WorkflowState(
                repository_id=repository_id,
                stage=stage,
                status=status,
                updated_at=datetime.now(timezone.utc),
            )
        )
