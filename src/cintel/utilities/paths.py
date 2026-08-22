from __future__ import annotations

import fnmatch
from pathlib import Path

from cintel.utilities.hashing import stable_id


def normalized_path(path: Path, base: Path | None = None) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute() and base is not None:
        candidate = base / candidate
    return candidate.resolve(strict=False)


def repository_relative(path: Path, repository_root: Path) -> str | None:
    try:
        return path.resolve(strict=False).relative_to(
            repository_root.resolve(strict=False)
        ).as_posix()
    except ValueError:
        return None


def stable_repository_id(repository_root: str | Path) -> str:
    return stable_id("repository", str(Path(repository_root).expanduser().resolve()))


def is_excluded(relative_path: Path, patterns: tuple[str, ...]) -> bool:
    text = relative_path.as_posix()
    return any(
        fnmatch.fnmatch(relative_path.name, pattern)
        or fnmatch.fnmatch(text, pattern)
        or any(fnmatch.fnmatch(part, pattern) for part in relative_path.parts)
        for pattern in patterns
    )
