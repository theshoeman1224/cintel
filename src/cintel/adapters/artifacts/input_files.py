from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from cintel.domain.errors import InputArtifactError
from cintel.domain.models import (
    ArtifactValidationStatus,
    InputArtifact,
    InputArtifactType,
    StalenessStatus,
)
from cintel.utilities.hashing import stable_id
from cintel.adapters.artifacts.validation import validate_artifact


class FileSystemInputArtifactProvider:
    """Copies user evidence into the workspace and validates conservative structure."""

    def import_artifact(
        self,
        source_path: str,
        artifact_type: InputArtifactType,
        destination_directory: str,
        repository_id: str,
        repository_root: str,
        build_configuration_id: str | None = None,
        command_used: tuple[str, ...] | None = None,
        working_directory: str | None = None,
    ) -> InputArtifact:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise InputArtifactError(f"Input artifact does not exist: {source}")
        try:
            content = source.read_bytes()
        except OSError as error:
            raise InputArtifactError(f"Cannot read input artifact {source}: {error}") from error
        digest = hashlib.sha256(content).hexdigest()
        destination_root = Path(destination_directory).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / f"{digest[:12]}-{source.name}"
        if source != destination:
            try:
                shutil.copyfile(source, destination)
            except OSError as error:
                raise InputArtifactError(
                    f"Cannot preserve input artifact under {destination_root}: {error}"
                ) from error
        text = content.decode("utf-8", errors="replace")
        valid, messages = validate_artifact(artifact_type, text, Path(repository_root))
        return InputArtifact(
            id=stable_id("input-artifact", repository_id, artifact_type.value, digest),
            repository_id=repository_id,
            artifact_type=artifact_type,
            file_path=str(destination),
            source=str(source),
            command_used=command_used,
            working_directory=working_directory,
            content_hash=digest,
            creation_time=datetime.now(timezone.utc),
            validation_status=(
                ArtifactValidationStatus.VALID if valid else ArtifactValidationStatus.INVALID
            ),
            validation_messages=messages,
            build_configuration_id=build_configuration_id,
            staleness_status=StalenessStatus.CURRENT,
        )

    def refresh_staleness(self, artifact: InputArtifact) -> InputArtifact:
        path = Path(artifact.file_path)
        if not path.is_file():
            return replace(
                artifact,
                staleness_status=StalenessStatus.STALE,
                validation_messages=artifact.validation_messages
                + ("Preserved artifact file is missing.",),
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source = Path(artifact.source)
        source_changed = (
            source.is_file()
            and source.resolve() != path.resolve()
            and hashlib.sha256(source.read_bytes()).hexdigest() != artifact.content_hash
        )
        return replace(
            artifact,
            staleness_status=(
                StalenessStatus.CURRENT
                if digest == artifact.content_hash and not source_changed
                else StalenessStatus.STALE
            ),
        )

    def read_text(self, artifact: InputArtifact) -> str:
        try:
            return Path(artifact.file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise InputArtifactError(
                f"Cannot read preserved input artifact {artifact.file_path}: {error}"
            ) from error
