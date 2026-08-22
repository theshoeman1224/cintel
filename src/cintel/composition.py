from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cintel.adapters.ai import DisabledAIProvider
from cintel.adapters.artifacts import FileSystemArtifactWriter, FileSystemInputArtifactProvider
from cintel.adapters.build import MakeBuildDiscovery
from cintel.adapters.commands import SubprocessCommandRunner
from cintel.adapters.compiler import (
    GCCCompilerCommandParser,
    GCCCompilerMetadataProvider,
)
from cintel.adapters.guidance import StandardInputGuidanceProvider
from cintel.adapters.reports import (
    JSONReportRenderer,
    MarkdownGuidanceRenderer,
    MarkdownReportRenderer,
)
from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application import (
    BuildDiscoveryService,
    DoctorService,
    InitializationService,
    GuidedRecoveryService,
    RepositoryScanService,
)


@dataclass(frozen=True, slots=True)
class Application:
    doctor: DoctorService
    initialization: InitializationService
    scanning: RepositoryScanService
    build_discovery: BuildDiscoveryService
    recovery: GuidedRecoveryService
    ai_provider: DisabledAIProvider
    storage_factory: Callable[[Path], SQLiteAnalysisStorage]


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
    build_service = BuildDiscoveryService(
        provider=make_discovery,
        storage_factory=SQLiteAnalysisStorage,
        repository_scanner=scanner,
    )
    return Application(
        doctor=DoctorService(command_runner),
        initialization=InitializationService(),
        scanning=scanner,
        build_discovery=build_service,
        recovery=GuidedRecoveryService(
            scanner=scanner,
            build_discovery=build_service,
            artifact_provider=FileSystemInputArtifactProvider(),
            guidance_provider=StandardInputGuidanceProvider(),
            guidance_renderer=MarkdownGuidanceRenderer(),
            artifact_writer=FileSystemArtifactWriter(),
            storage_factory=SQLiteAnalysisStorage,
        ),
        ai_provider=DisabledAIProvider(),
        storage_factory=SQLiteAnalysisStorage,
    )
