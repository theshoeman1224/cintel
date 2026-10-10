"""AI provider that refuses generation. The deterministic core never depends on it."""

from cintel.domain.errors import AIUnavailableError
from cintel.domain.models import ContextPackage


class DisabledAIProvider:
    """AI provider that refuses every generation request."""
    @property
    def enabled(self) -> bool:
        return False

    def generate(self, prompt: str, context: ContextPackage) -> str:
        raise AIUnavailableError(
            "AI support is disabled. Deterministic analysis does not require an AI provider."
        )

