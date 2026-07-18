from dataclasses import dataclass


DEFAULT_EXCLUSIONS = (
    ".git",
    ".code-intelligence",
    "build",
    "dist",
    "out",
    "obj",
    "objects",
    "cmake-build-*",
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    repository_root: str
    output_directory: str
    database_path: str
    exclusion_patterns: tuple[str, ...] = DEFAULT_EXCLUSIONS
    ai_enabled: bool = False

