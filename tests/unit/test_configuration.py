import tempfile
import unittest
from pathlib import Path

from cintel.configuration.loader import default_config, load_config, render_config
from cintel.domain.errors import ConfigurationError


class ConfigurationTests(unittest.TestCase):
    def test_round_trip_initial_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = default_config(root)
            path = root / "config.toml"
            path.write_text(render_config(config), encoding="utf-8")

            loaded = load_config(path)

            self.assertEqual(config, loaded)
            self.assertFalse(loaded.ai_enabled)

    def test_invalid_toml_raises_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[broken", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(path)

