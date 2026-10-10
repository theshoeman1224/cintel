"""Diagnostic read/write helpers shared by the storage mixins."""

from __future__ import annotations

import json
import sqlite3

from cintel.adapters.storage.serialization import (
    diagnostic_from_dict,
    diagnostic_to_dict,
)
from cintel.domain.diagnostics import Diagnostic


def replace_diagnostics(
    connection: sqlite3.Connection,
    repository_id: str,
    diagnostics: tuple[Diagnostic, ...],
    context: str,
) -> None:
    """Delete and reinsert one context's diagnostics."""
    connection.execute(
        "DELETE FROM diagnostics WHERE repository_id = ? AND context_key = ?",
        (repository_id, context),
    )
    connection.executemany(
        """
        INSERT INTO diagnostics
          (repository_id, code, severity, message, payload, context_key)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            (
                repository_id,
                item.code,
                item.severity.value,
                item.message,
                json.dumps(diagnostic_to_dict(item), sort_keys=True),
                context,
            )
            for item in diagnostics
        ),
    )



def read_diagnostics(
    connection: sqlite3.Connection,
    repository_id: str,
    *,
    exact_context: str | None = None,
    context_prefix: str | None = None,
) -> tuple[Diagnostic, ...]:
    """Read diagnostics by exact context or context prefix."""
    query = (
        "SELECT code, severity, message, payload FROM diagnostics "
        "WHERE repository_id = ?"
    )
    arguments: list[str] = [repository_id]
    if exact_context is not None:
        query += " AND context_key = ?"
        arguments.append(exact_context)
    elif context_prefix is not None:
        query += " AND context_key LIKE ?"
        arguments.append(f"{context_prefix}%")
    query += " ORDER BY id"
    rows = connection.execute(query, tuple(arguments)).fetchall()
    results = []
    for code, severity, message, payload in rows:
        data = json.loads(payload)
        data.update({"code": code, "severity": severity, "message": message})
        results.append(diagnostic_from_dict(data))
    return tuple(results)



def load_diagnostics(
    connection: sqlite3.Connection, repository_id: str, context: str
) -> tuple[Diagnostic, ...]:
    """Read diagnostics for one exact context key."""
    return read_diagnostics(connection, repository_id, exact_context=context)


