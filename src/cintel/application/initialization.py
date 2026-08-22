from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cintel.application.storage_session import storage_session
from cintel.configuration.loader import default_config, render_config
from cintel.configuration.models import AppConfig
from cintel.domain.errors import InitializationError
from cintel.domain.models import Repository
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.paths import stable_repository_id

OUTPUT_DIRECTORIES = (
    "files",
    "folders",
    "symbols",
    "graphs",
    "context",
    "input",
    "cache",
    "reports",
)


@dataclass(frozen=True, slots=True)
class InitializationResult:
    config: AppConfig
    repository: Repository
    created_paths: tuple[str, ...]
    existing_paths: tuple[str, ...]


class InitializationService:
    def initialize(
        self,
        repository_root: Path,
        storage_factory: Callable[[Path], AnalysisStorage],
        output_directory: Path | None = None,
    ) -> InitializationResult:
        root = repository_root.expanduser().resolve()
        if not root.exists():
            raise InitializationError(f"Repository does not exist: {root}")
        if not root.is_dir():
            raise InitializationError(f"Repository path is not a directory: {root}")

        config = default_config(root, output_directory)
        output = Path(config.output_directory)

        created: list[str] = []
        existing: list[str] = []
        if output.exists() and not output.is_dir():
            raise InitializationError(f"Output path is not a directory: {output}")
        config_path = output / "config.toml"
        desired_config = render_config(config)
        if config_path.exists() and config_path.read_text(encoding="utf-8") != desired_config:
            raise InitializationError(
                f"Refusing to overwrite existing configuration: {config_path}"
            )
        if output.exists():
            existing.append(str(output))
        else:
            output.mkdir(parents=True)
            created.append(str(output))

        for name in OUTPUT_DIRECTORIES:
            path = output / name
            if path.exists():
                if not path.is_dir():
                    raise InitializationError(f"Expected a directory but found a file: {path}")
                existing.append(str(path))
            else:
                path.mkdir()
                created.append(str(path))

        if config_path.exists():
            existing.append(str(config_path))
        else:
            config_path.write_text(desired_config, encoding="utf-8")
            created.append(str(config_path))

        repository = Repository(
            id=stable_repository_id(root),
            root=str(root),
            name=root.name,
            created_at=datetime.now(timezone.utc),
        )
        with storage_session(storage_factory, config.database_path) as storage:
            database_existed = Path(config.database_path).exists()
            storage.save_repository(repository)
            target = existing if database_existed else created
            target.append(config.database_path)

        return InitializationResult(
            config=config,
            repository=repository,
            created_paths=tuple(created),
            existing_paths=tuple(existing),
        )
