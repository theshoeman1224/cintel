from dataclasses import dataclass

from cintel.adapters.ai import DisabledAIProvider
from cintel.adapters.artifacts import FileSystemArtifactWriter
from cintel.adapters.commands import SubprocessCommandRunner
from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application import DoctorService, InitializationService, RepositoryScanService


@dataclass(frozen=True, slots=True)
class Application:
    doctor: DoctorService
    initialization: InitializationService
    scanning: RepositoryScanService
    ai_provider: DisabledAIProvider
    storage_factory: type[SQLiteAnalysisStorage]


def create_application() -> Application:
    command_runner = SubprocessCommandRunner()
    return Application(
        doctor=DoctorService(command_runner),
        initialization=InitializationService(),
        scanning=RepositoryScanService(
            discovery=FileSystemRepositoryDiscovery(),
            markdown_renderer=MarkdownReportRenderer(),
            json_renderer=JSONReportRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        ),
        ai_provider=DisabledAIProvider(),
        storage_factory=SQLiteAnalysisStorage,
    )
