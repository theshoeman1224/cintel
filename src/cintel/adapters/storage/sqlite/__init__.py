"""SQLite storage facade.

One facade, one connection, and one mixin per aggregate so the schema and
its read/write code stay together. The public class name and constructor
signature are unchanged.
"""

from cintel.adapters.storage.sqlite.analysis_store import AnalysisStore
from cintel.adapters.storage.sqlite.base import SQLiteConnection
from cintel.adapters.storage.sqlite.build_store import BuildStore
from cintel.adapters.storage.sqlite.repository_store import RepositoryStore
from cintel.adapters.storage.sqlite.workflow_store import WorkflowStore


class SQLiteAnalysisStorage(
    SQLiteConnection,
    RepositoryStore,
    BuildStore,
    AnalysisStore,
    WorkflowStore,
):
    """Persist and query all repository state in one SQLite database."""
