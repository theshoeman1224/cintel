import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.artifacts import (
    FileSystemArtifactWriter,
    FileSystemInputArtifactProvider,
)
from cintel.adapters.guidance import StandardInputGuidanceProvider
from cintel.adapters.reports import MarkdownGuidanceRenderer
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application.recovery import (
    GuidedRecoveryService,
    parse_path_placeholders,
)
from cintel.application.scanning import ScanWorkflowResult
from cintel.configuration.models import AppConfig
from cintel.domain.models import (
    ArtifactValidationStatus,
    BuildConfiguration,
    BuildDiscoveryResult,
    Repository,
    RepositoryScan,
    StalenessStatus,
    WorkflowStatus,
)
from cintel.utilities.hashing import stable_id


class _FakeScanner:
    def __init__(self, scan: RepositoryScan, storage_factory) -> None:
        self._scan = scan
        self._storage_factory = storage_factory

    def scan(self, config: AppConfig) -> ScanWorkflowResult:
        storage = self._storage_factory(Path(config.database_path))
        storage.initialize()
        try:
            if storage.get_repository(self._scan.repository.id) is None:
                storage.save_repository(self._scan.repository)
        finally:
            storage.close()
        return ScanWorkflowResult(
            scan=self._scan, markdown_report=None, json_report=None
        )


class _RecordingBuildDiscovery:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.saved_outputs: list[tuple[str, str]] = []

    def preview(self, configuration: BuildConfiguration) -> tuple[str, ...]:
        self.preview_calls += 1
        return ("make", "-n")

    def discover_saved(
        self,
        app_config: AppConfig,
        configuration: BuildConfiguration,
        raw_output: str,
        artifact_hash: str,
    ) -> BuildDiscoveryResult:
        self.saved_outputs.append((raw_output, artifact_hash))
        return BuildDiscoveryResult(
            configuration=configuration,
            make_arguments=("make", "-n"),
            raw_output=raw_output,
            raw_error="",
            exit_code=0,
            duration_seconds=0.0,
            commands=(),
            compiler_invocations=(),
            compilation_units=(),
            diagnostics=(),
            capabilities=(),
            input_fingerprint="input-fingerprint",
            build_fingerprint="build-fingerprint",
            discovered_at=datetime.now(timezone.utc),
        )


class GuidedRecoveryServiceTests(unittest.TestCase):
    def _service(self, root: Path):
        repository_root = root / "repo"
        repository_root.mkdir()
        output = root / "analysis"
        app_config = AppConfig(
            repository_root=str(repository_root),
            output_directory=str(output),
            database_path=str(output / "index.sqlite"),
        )
        repository = Repository(
            id=stable_id("repository", str(repository_root.resolve())),
            root=str(repository_root),
            name="repo",
            created_at=datetime.now(timezone.utc),
        )
        scan = RepositoryScan(
            repository=repository,
            files=(),
            diagnostics=(),
            capabilities=(),
            scanned_at=datetime.now(timezone.utc),
            hashes_computed=0,
            hashes_reused=0,
        )
        discovery = _RecordingBuildDiscovery()
        service = GuidedRecoveryService(
            scanner=_FakeScanner(scan, SQLiteAnalysisStorage),
            build_discovery=discovery,
            artifact_provider=FileSystemInputArtifactProvider(),
            guidance_provider=StandardInputGuidanceProvider(),
            guidance_renderer=MarkdownGuidanceRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        )
        return app_config, service, discovery

    def _configuration(self, app_config: AppConfig, name: str) -> BuildConfiguration:
        return BuildConfiguration(
            id=f"build-{name}",
            repository_id=stable_id(
                "repository", str(Path(app_config.repository_root).resolve())
            ),
            name=name,
            repository_root=app_config.repository_root,
            makefile="Makefile",
            working_directory=app_config.repository_root,
        )

    def _stored_states(self, app_config: AppConfig, repository_id: str):
        storage = SQLiteAnalysisStorage(Path(app_config.database_path))
        storage.initialize()
        try:
            return {state.stage: state.status for state in storage.list_workflow_states(repository_id)}
        finally:
            storage.close()

    def test_resume_without_evidence_reports_missing_build_and_writes_required_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_config, service, discovery = self._service(Path(directory))
            result = service.resume(app_config, None)

            codes = {item.code for item in result.diagnostics}
            self.assertIn("CI-INPUT-001", codes)
            self.assertIs(WorkflowStatus.REDUCED, result.status)
            self.assertIsNone(result.interrupted_stage)
            report = Path(app_config.output_directory) / "REQUIRED_INPUTS.md"
            self.assertTrue(report.is_file())
            self.assertIn("Required inputs", report.read_text(encoding="utf-8"))
            states = self._stored_states(app_config, result.repository_id)
            self.assertEqual(WorkflowStatus.REDUCED, states["input_validation"])
            self.assertEqual(WorkflowStatus.REDUCED, states["guided_recovery"])

    def test_setup_records_completed_scan_and_pending_recovery_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_config, service, discovery = self._service(Path(directory))
            result = service.setup(app_config, None)

            states = self._stored_states(app_config, result.repository_id)
            self.assertEqual(WorkflowStatus.COMPLETED, states["repository_scan"])
            self.assertEqual(WorkflowStatus.PENDING, states["guided_recovery"])
            self.assertIn("repository_scan", result.completed_stages)
            self.assertEqual(0, discovery.preview_calls)

    def test_invalid_import_interrupts_with_input_002(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            source = root / "empty-dry-run.txt"
            source.write_text("", encoding="utf-8")

            result = service.resume(app_config, None, input_file=source)

            codes = {item.code for item in result.diagnostics}
            self.assertIn("CI-INPUT-002", codes)
            self.assertIs(WorkflowStatus.INTERRUPTED, result.status)
            self.assertEqual("input_validation", result.interrupted_stage)
            self.assertEqual(0, len(discovery.saved_outputs))

    def test_valid_make_dry_run_flows_through_saved_discovery_with_placeholder_replaced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            configuration = self._configuration(app_config, "linux")
            source = root / "dry-run.txt"
            placeholder_root = "<FIXTURE_ROOT>"
            real_root = app_config.repository_root
            source.write_text(f"gcc -c {placeholder_root}/src/main.c -o main.o\n", encoding="utf-8")

            result = service.resume(
                app_config, configuration, input_file=source
            )

            self.assertEqual(1, len(discovery.saved_outputs))
            raw_output, artifact_hash = discovery.saved_outputs[0]
            self.assertNotIn(placeholder_root, raw_output)
            self.assertIn(real_root, raw_output)
            stored_artifact = result.artifacts[-1]
            self.assertEqual(stored_artifact.content_hash, artifact_hash)

    def test_modified_preserved_artifact_is_flagged_stale_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            source = root / "dry-run.txt"
            source.write_text("gcc -c src/main.c -o main.o\n", encoding="utf-8")
            first = service.resume(app_config, None, input_file=source)
            preserved = first.artifacts[-1].file_path

            Path(preserved).write_text("modified after import\n", encoding="utf-8")
            second = service.resume(app_config, None)

            codes = {item.code for item in second.diagnostics}
            self.assertIn("CI-INPUT-003", codes)
            stale = [item for item in second.artifacts if item.file_path == preserved]
            self.assertEqual(1, len(stale))
            self.assertIs(StalenessStatus.STALE, stale[0].staleness_status)

    def test_artifact_from_other_build_configuration_is_marked_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            configuration_a = self._configuration(app_config, "linux")
            source = root / "dry-run.txt"
            source.write_text("gcc -c src/main.c -o main.o\n", encoding="utf-8")
            imported = service.resume(app_config, configuration_a, input_file=source)
            self.assertIs(
                ArtifactValidationStatus.VALID,
                imported.artifacts[-1].validation_status,
            )

            configuration_b = self._configuration(app_config, "debug")
            resumed = service.resume(app_config, configuration_b)

            codes = {item.code for item in resumed.diagnostics}
            self.assertIn("CI-INPUT-003", codes)
            mismatched = [
                item
                for item in resumed.artifacts
                if item.build_configuration_id == configuration_a.id
            ]
            self.assertEqual(1, len(mismatched))
            self.assertIs(StalenessStatus.STALE, mismatched[0].staleness_status)
            self.assertIn(
                "different build configuration",
                " ".join(mismatched[0].validation_messages),
            )

    def test_custom_path_placeholders_are_applied_to_saved_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            configuration = self._configuration(app_config, "linux")
            source = root / "dry-run.txt"
            source.write_text(
                "gcc -c @BUILD_ROOT@/src/main.c -o main.o\n", encoding="utf-8"
            )

            service.resume(
                app_config,
                configuration,
                input_file=source,
                path_placeholders=(("@BUILD_ROOT@", app_config.repository_root),),
            )

            self.assertEqual(1, len(discovery.saved_outputs))
            raw_output, _ = discovery.saved_outputs[0]
            self.assertNotIn("@BUILD_ROOT@", raw_output)
            self.assertIn(app_config.repository_root, raw_output)

    def test_placeholder_parsing_rejects_malformed_values(self) -> None:
        from cintel.domain.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            parse_path_placeholders(["missing-separator"], "--path-placeholder")
        with self.assertRaises(ConfigurationError):
            parse_path_placeholders(["=target"], "--path-placeholder")
        self.assertEqual(
            (("<FIXTURE_ROOT>", "/repo"),),
            parse_path_placeholders(["<FIXTURE_ROOT>=/repo"], "--path-placeholder"),
        )

    def test_instructions_regenerate_the_report_without_importing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_config, service, discovery = self._service(root)
            source = root / "dry-run.txt"
            source.write_text("gcc -c src/main.c -o main.o\n", encoding="utf-8")
            imported = service.resume(app_config, None, input_file=source)
            report_path = Path(imported.required_inputs_report)
            content_before = report_path.read_text(encoding="utf-8")

            regenerated = service.instructions(app_config, None)

            self.assertEqual(1, len(regenerated.artifacts))
            self.assertEqual(0, len(discovery.saved_outputs))
            self.assertEqual(
                content_before, report_path.read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    unittest.main()
