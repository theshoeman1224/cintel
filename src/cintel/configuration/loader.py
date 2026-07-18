from __future__ import annotations

import tomllib
from pathlib import Path

from cintel.configuration.models import AppConfig, DEFAULT_EXCLUSIONS
from cintel.domain.errors import ConfigurationError

DEFAULT_CONFIG_NAME = "config.toml"


def default_output_directory(repository_root: Path) -> Path:
    return repository_root / ".code-intelligence"


def default_config(repository_root: Path, output_directory: Path | None = None) -> AppConfig:
    root = repository_root.expanduser().resolve()
    output = (output_directory or default_output_directory(root)).expanduser().resolve()
    return AppConfig(
        repository_root=str(root),
        output_directory=str(output),
        database_path=str(output / "index.sqlite"),
    )


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc

    try:
        repository = Path(raw["repository"]["root"]).expanduser().resolve()
        output = Path(raw["output"]["directory"]).expanduser()
        if not output.is_absolute():
            output = repository / output
        database = Path(raw["storage"].get("database", "index.sqlite")).expanduser()
        if not database.is_absolute():
            database = output / database
        exclusions = tuple(raw.get("scan", {}).get("exclude", DEFAULT_EXCLUSIONS))
        ai_enabled = bool(raw.get("ai", {}).get("enabled", False))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ConfigurationError(f"Missing or invalid configuration value in {path}") from exc

    return AppConfig(
        repository_root=str(repository),
        output_directory=str(output.resolve()),
        database_path=str(database.resolve()),
        exclusion_patterns=exclusions,
        ai_enabled=ai_enabled,
    )


def render_config(config: AppConfig) -> str:
    exclusions = ", ".join(_toml_string(item) for item in config.exclusion_patterns)
    return "\n".join(
        (
            "# Legacy C Code Intelligence configuration",
            "[repository]",
            f"root = {_toml_string(config.repository_root)}",
            "",
            "[output]",
            f"directory = {_toml_string(config.output_directory)}",
            "",
            "[storage]",
            f"database = {_toml_string(config.database_path)}",
            "",
            "[scan]",
            f"exclude = [{exclusions}]",
            "",
            "[ai]",
            "enabled = false",
            "",
        )
    )


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'

