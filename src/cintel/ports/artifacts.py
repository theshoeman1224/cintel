"""Output-writing contract used by scanners, reports, and context packages."""

from pathlib import Path
from typing import Protocol


class ArtifactWriter(Protocol):
    """Write generated text to a path inside the workspace."""

    def write_text(self, path: Path, content: str) -> None:
        """Write content, creating parent directories as needed."""
        ...
