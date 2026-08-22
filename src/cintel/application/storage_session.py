from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

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
