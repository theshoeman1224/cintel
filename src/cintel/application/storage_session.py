from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from cintel.ports.storage import AnalysisStorage


@contextmanager
def storage_session(
    factory: Callable[[Path], AnalysisStorage], database_path: str | Path
) -> Iterator[AnalysisStorage]:
    storage = factory(Path(database_path))
    storage.initialize()
    try:
        yield storage
    finally:
        storage.close()
