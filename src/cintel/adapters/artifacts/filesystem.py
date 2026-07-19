from pathlib import Path


class FileSystemArtifactWriter:
    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
