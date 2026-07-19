from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cintel.configuration.models import AppConfig
from cintel.domain.models import GeneratedReportMetadata, RepositoryScan
from cintel.ports.artifacts import ArtifactWriter
from cintel.ports.services import ReportRenderer, RepositoryDiscoveryProvider
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.hashing import sha256_text, stable_id


@dataclass(frozen=True, slots=True)
class ScanWorkflowResult:
    scan: RepositoryScan
    markdown_report: str | None
    json_report: str | None


class RepositoryScanService:
    def __init__(
        self,
        discovery: RepositoryDiscoveryProvider,
        markdown_renderer: ReportRenderer,
        json_renderer: ReportRenderer,
        artifact_writer: ArtifactWriter,
        storage_factory: Callable[[Path], AnalysisStorage],
    ) -> None:
        self._discovery = discovery
        self._markdown_renderer = markdown_renderer
        self._json_renderer = json_renderer
        self._artifact_writer = artifact_writer
        self._storage_factory = storage_factory

    def scan(self, config: AppConfig) -> ScanWorkflowResult:
        root = Path(config.repository_root)
        repository_id = stable_id("repository", str(root.resolve(strict=False)))
        if not root.is_dir():
            result = self._discovery.discover(
                str(root), repository_id, config.exclusion_patterns
            )
            return ScanWorkflowResult(result, None, None)

        storage = self._storage_factory(Path(config.database_path))
        try:
            storage.initialize()
            previous = storage.list_repository_files(repository_id)
            result = self._discovery.discover(
                str(root),
                repository_id,
                config.exclusion_patterns,
                previous,
            )
            storage.save_repository(result.repository)
            storage.replace_repository_files(repository_id, result.files)
            storage.save_diagnostics(repository_id, result.diagnostics)
            storage.save_capabilities(repository_id, result.capabilities)

            markdown = self._markdown_renderer.render("repository_inventory", result)
            json_content = self._json_renderer.render("repository_inventory", result)
            output = Path(config.output_directory)
            markdown_path = output / "repository.md"
            json_path = output / "reports" / "repository.json"
            self._artifact_writer.write_text(markdown_path, markdown)
            self._artifact_writer.write_text(json_path, json_content)
            for report_format, path, content in (
                ("markdown", markdown_path, markdown),
                ("json", json_path, json_content),
            ):
                storage.save_report_metadata(
                    GeneratedReportMetadata(
                        id=stable_id(
                            "report",
                            repository_id,
                            "repository_inventory",
                            report_format,
                        ),
                        repository_id=repository_id,
                        report_name="repository_inventory",
                        format=report_format,
                        file_path=str(path.resolve()),
                        content_sha256=sha256_text(content),
                        generated_at=result.scanned_at,
                    )
                )
            return ScanWorkflowResult(
                scan=result,
                markdown_report=str(markdown_path.resolve()),
                json_report=str(json_path.resolve()),
            )
        finally:
            storage.close()
