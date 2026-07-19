from pathlib import Path
from typing import Protocol


class ArtifactWriter(Protocol):
    def write_text(self, path: Path, content: str) -> None: ...
