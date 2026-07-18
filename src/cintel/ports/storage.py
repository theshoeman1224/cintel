from typing import Protocol

from cintel.domain.diagnostics import Diagnostic
from cintel.domain.models import AnalysisCapability, Repository


class AnalysisStorage(Protocol):
    def initialize(self) -> None: ...

    def close(self) -> None: ...

    def save_repository(self, repository: Repository) -> None: ...

    def get_repository(self, repository_id: str) -> Repository | None: ...

    def save_diagnostics(
        self, repository_id: str, diagnostics: tuple[Diagnostic, ...]
    ) -> None: ...

    def save_capabilities(
        self, repository_id: str, capabilities: tuple[AnalysisCapability, ...]
    ) -> None: ...

    def schema_version(self) -> int: ...

