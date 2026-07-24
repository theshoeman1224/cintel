import tempfile
import unittest
from pathlib import Path

from cintel.adapters.artifacts import FileSystemInputArtifactProvider
from cintel.domain.models import (
    ArtifactValidationStatus,
    InputArtifactType,
    StalenessStatus,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "complex_c_project"
SAMPLES = FIXTURE / "expected" / "sample_inputs"


class InputArtifactTests(unittest.TestCase):
    def test_validates_every_supported_artifact_type_using_complex_fixture(self) -> None:
        samples = {
            InputArtifactType.MAKE_DRY_RUN: "make-linux-dry-run.txt",
            InputArtifactType.BUILD_LOG: "verbose-build.log",
            InputArtifactType.FILE_LIST: "repository-files.txt",
            InputArtifactType.DEPENDENCY_FILE: "application.d",
            InputArtifactType.PREPROCESSED_SOURCE: "application.i",
            InputArtifactType.MACRO_LISTING: "macros.txt",
        }
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            artifacts = tuple(
                provider.import_artifact(
                    str(SAMPLES / filename),
                    artifact_type,
                    directory,
                    "repository-1",
                    str(FIXTURE),
                )
                for artifact_type, filename in samples.items()
            )
        self.assertEqual(6, len(artifacts))
        self.assertTrue(
            all(item.validation_status is ArtifactValidationStatus.VALID for item in artifacts)
        )
        self.assertEqual(6, len({item.content_hash for item in artifacts}))

    def test_rejects_empty_input_and_detects_preserved_file_changes(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.txt"
            empty.write_text("", encoding="utf-8")
            artifact = provider.import_artifact(
                str(empty),
                InputArtifactType.MAKE_DRY_RUN,
                str(root / "input"),
                "repository-1",
                str(FIXTURE),
            )
            self.assertIs(ArtifactValidationStatus.INVALID, artifact.validation_status)
            Path(artifact.file_path).write_text("changed", encoding="utf-8")
            refreshed = provider.refresh_staleness(artifact)
            self.assertIs(StalenessStatus.STALE, refreshed.staleness_status)


if __name__ == "__main__":
    unittest.main()
