import tempfile
import unittest
from pathlib import Path

from cintel.adapters.storage import SCHEMA_VERSION, SQLiteAnalysisStorage
from cintel.application.initialization import InitializationService
from cintel.configuration.loader import load_config
from cintel.domain.errors import InitializationError


class InitializationIntegrationTests(unittest.TestCase):
    def test_initializes_idempotently_and_creates_valid_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "legacy"
            root.mkdir()
            service = InitializationService()

            first = service.initialize(root, SQLiteAnalysisStorage)
            second = service.initialize(root, SQLiteAnalysisStorage)

            output = root / ".code-intelligence"
            self.assertTrue((output / "config.toml").is_file())
            self.assertTrue((output / "index.sqlite").is_file())
            self.assertGreater(len(first.created_paths), 0)
            self.assertGreater(len(second.existing_paths), 0)
            self.assertEqual(first.config, load_config(output / "config.toml"))
            storage = SQLiteAnalysisStorage(output / "index.sqlite")
            storage.initialize()
            self.assertEqual(SCHEMA_VERSION, storage.schema_version())
            storage.close()

    def test_refuses_to_overwrite_changed_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / ".code-intelligence"
            config_dir.mkdir()
            (config_dir / "config.toml").write_text("# user settings\n", encoding="utf-8")

            with self.assertRaises(InitializationError):
                InitializationService().initialize(root, SQLiteAnalysisStorage)
            self.assertFalse((config_dir / "cache").exists())

    def test_allows_an_explicit_external_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repository"
            output = base / "analysis-output"
            root.mkdir()
            result = InitializationService().initialize(
                root, SQLiteAnalysisStorage, output
            )
            self.assertEqual(str(output.resolve()), result.config.output_directory)
            self.assertTrue((output / "config.toml").is_file())
