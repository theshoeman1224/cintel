from cintel.domain.errors import AIUnavailableError
from cintel.domain.models import ContextPackage


class DisabledAIProvider:
    @property
    def enabled(self) -> bool:
        return False

    def generate(self, prompt: str, context: ContextPackage) -> str:
        raise AIUnavailableError(
            "AI support is disabled. Deterministic analysis does not require an AI provider."
        )

