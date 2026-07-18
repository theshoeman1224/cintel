from pathlib import Path


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

