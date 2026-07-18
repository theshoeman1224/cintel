import unittest

from cintel.adapters.ai import DisabledAIProvider
from cintel.domain.errors import AIUnavailableError


class DisabledAIProviderTests(unittest.TestCase):
    def test_is_explicitly_disabled(self) -> None:
        provider = DisabledAIProvider()
        self.assertFalse(provider.enabled)
        with self.assertRaises(AIUnavailableError):
            provider.generate("prompt", None)  # type: ignore[arg-type]

