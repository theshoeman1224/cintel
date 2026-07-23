from dataclasses import dataclass

from cintel.adapters.ai import DisabledAIProvider
from cintel.adapters.artifacts import FileSystemArtifactWriter
from cintel.adapters.build import MakeBuildDiscovery
from cintel.adapters.commands import SubprocessCommandRunner
from cintel.adapters.compiler import (
    GCCCompilerCommandParser,
    GCCCompilerMetadataProvider,
)
from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application import (
    BuildDiscoveryService,
    DoctorService,
    InitializationService,
    RepositoryScanService,
)


@dataclass(frozen=True, slots=True)
class Application:
    doctor: DoctorService
    initialization: InitializationService
    scanning: RepositoryScanService
    build_discovery: BuildDiscoveryService
    ai_provider: DisabledAIProvider
    storage_factory: type[SQLiteAnalysisStorage]


def create_application() -> Application:
    command_runner = SubprocessCommandRunner()
    scanner = RepositoryScanService(
        discovery=FileSystemRepositoryDiscovery(),
        markdown_renderer=MarkdownReportRenderer(),
        json_renderer=JSONReportRenderer(),
        artifact_writer=FileSystemArtifactWriter(),
        storage_factory=SQLiteAnalysisStorage,
    )
    make_discovery = MakeBuildDiscovery(
        command_runner=command_runner,
        compiler_parser=GCCCompilerCommandParser(),
        compiler_metadata=GCCCompilerMetadataProvider(command_runner),
    )
    return Application(
        doctor=DoctorService(command_runner),
        initialization=InitializationService(),
        scanning=scanner,
        build_discovery=BuildDiscoveryService(
            provider=make_discovery,
            storage_factory=SQLiteAnalysisStorage,
            repository_scanner=scanner,
        ),
        ai_provider=DisabledAIProvider(),
        storage_factory=SQLiteAnalysisStorage,
    )
