"""Adapters for writing artifacts and importing evidence."""

from cintel.adapters.artifacts.filesystem import FileSystemArtifactWriter
from cintel.adapters.artifacts.input_files import FileSystemInputArtifactProvider

__all__ = ["FileSystemArtifactWriter", "FileSystemInputArtifactProvider"]
