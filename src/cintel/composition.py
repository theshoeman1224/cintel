from dataclasses import dataclass

from cintel.adapters.ai import DisabledAIProvider
from cintel.adapters.commands import SubprocessCommandRunner
from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.application import DoctorService, InitializationService


@dataclass(frozen=True, slots=True)
class Application:
    doctor: DoctorService
    initialization: InitializationService
    ai_provider: DisabledAIProvider
    storage_factory: type[SQLiteAnalysisStorage]


def create_application() -> Application:
    command_runner = SubprocessCommandRunner()
    return Application(
        doctor=DoctorService(command_runner),
        initialization=InitializationService(),
        ai_provider=DisabledAIProvider(),
        storage_factory=SQLiteAnalysisStorage,
    )
