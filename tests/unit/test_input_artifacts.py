import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.artifacts import FileSystemInputArtifactProvider
from cintel.adapters.artifacts.validation import validate_artifact
from cintel.domain.errors import InputArtifactError
from cintel.domain.models import (
    ArtifactValidationStatus,
    InputArtifactType,
    StalenessStatus,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "complex_c_project"
SAMPLES = FIXTURE / "expected" / "sample_inputs"


def _import_dry_run(provider, root: Path):
    source = root / "dry-run.txt"
    source.write_text("gcc -c src/app/main.c -o build/main.o\n", encoding="utf-8")
    artifact = provider.import_artifact(
        str(source),
        InputArtifactType.MAKE_DRY_RUN,
        str(root / "input"),
        "repository-1",
        str(FIXTURE),
    )
    return artifact, source


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

    def test_import_rejects_missing_source_file(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.txt"
            with self.assertRaises(InputArtifactError) as caught:
                provider.import_artifact(
                    str(missing),
                    InputArtifactType.MAKE_DRY_RUN,
                    directory,
                    "repository-1",
                    str(FIXTURE),
                )
            self.assertIn("does not exist", str(caught.exception))

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "permission checks do not apply to root",
    )
    def test_import_reports_unreadable_source_file(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dry-run.txt"
            source.write_text("gcc -c main.c -o main.o\n", encoding="utf-8")
            os.chmod(source, 0o000)
            try:
                with self.assertRaises(InputArtifactError) as caught:
                    provider.import_artifact(
                        str(source),
                        InputArtifactType.MAKE_DRY_RUN,
                        str(root / "input"),
                        "repository-1",
                        str(FIXTURE),
                    )
            finally:
                os.chmod(source, 0o644)
            self.assertIn("Cannot read input artifact", str(caught.exception))

    def test_import_reports_copy_failure(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dry-run.txt"
            source.write_text("gcc -c main.c -o main.o\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            destination_root = root / "input"
            destination_root.mkdir()
            (destination_root / f"{digest[:12]}-{source.name}").mkdir()
            with self.assertRaises(InputArtifactError) as caught:
                provider.import_artifact(
                    str(source),
                    InputArtifactType.MAKE_DRY_RUN,
                    str(destination_root),
                    "repository-1",
                    str(FIXTURE),
                )
            self.assertIn("Cannot preserve input artifact", str(caught.exception))

    def test_read_text_reports_missing_preserved_file(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            artifact, _ = _import_dry_run(provider, Path(directory))
            Path(artifact.file_path).unlink()
            with self.assertRaises(InputArtifactError) as caught:
                provider.read_text(artifact)
            self.assertIn("Cannot read preserved input artifact", str(caught.exception))

    def test_refresh_staleness_marks_missing_preserved_file(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            artifact, _ = _import_dry_run(provider, Path(directory))
            Path(artifact.file_path).unlink()
            refreshed = provider.refresh_staleness(artifact)
            self.assertIs(StalenessStatus.STALE, refreshed.staleness_status)
            self.assertIn("Preserved artifact file is missing.", refreshed.validation_messages)

    def test_refresh_staleness_detects_changed_source(self) -> None:
        provider = FileSystemInputArtifactProvider()
        with tempfile.TemporaryDirectory() as directory:
            artifact, source = _import_dry_run(provider, Path(directory))
            source.write_text("gcc -c changed.c -o changed.o\n", encoding="utf-8")
            refreshed = provider.refresh_staleness(artifact)
            self.assertIs(StalenessStatus.STALE, refreshed.staleness_status)

    def test_validation_reports_missing_expected_structure(self) -> None:
        valid, messages = validate_artifact(
            InputArtifactType.FILE_LIST, "hello world", FIXTURE
        )
        self.assertFalse(valid)
        self.assertEqual(
            ("Input does not contain plausible C, header, or Make paths.",),
            messages,
        )

    def test_validation_warns_when_no_repository_source_is_recognized(self) -> None:
        text = "gcc -c unrelated.c -o unrelated.o\n"
        valid, messages = validate_artifact(
            InputArtifactType.MAKE_DRY_RUN, text, FIXTURE
        )
        self.assertTrue(valid)
        self.assertTrue(
            any("no selected repository source filename" in item for item in messages)
        )

    def test_validation_accepts_a_recognized_repository_source(self) -> None:
        text = "gcc -c src/app/main.c -o build/main.o\n"
        valid, messages = validate_artifact(
            InputArtifactType.MAKE_DRY_RUN, text, FIXTURE
        )
        self.assertTrue(valid)
        self.assertEqual(("Validated make_dry_run structure.",), messages)


if __name__ == "__main__":
    unittest.main()
