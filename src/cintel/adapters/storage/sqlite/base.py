"""Connection ownership for the SQLite storage facade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cintel.adapters.storage.migrations import SCHEMA_VERSION, migrate
from cintel.domain.errors import StorageError


class StoreBase:
    """Typing seam: stores read through the facade's single connection."""

    def _connect(self) -> sqlite3.Connection:
        raise NotImplementedError



class SQLiteConnection(StoreBase):
    """Own the database path and one lazily opened connection."""
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create or migrate the database; raise StorageError when unusable."""
        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current > SCHEMA_VERSION:
                raise StorageError(
                    f"Database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            migrate(connection, current)
            connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(f"Unable to initialize {self._database_path}: {exc}") from exc

    def close(self) -> None:
        """Release the connection; safe to call more than once."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def schema_version(self) -> int:
        """Stored schema version, 0 when uninitialized."""
        row = self._connect().execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._database_path)
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection
