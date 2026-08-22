import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.storage import SCHEMA_VERSION, SQLiteAnalysisStorage


_BASE_SCHEMA = """
CREATE TABLE repositories (
    id TEXT PRIMARY KEY,
    root TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE capabilities (
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,
    PRIMARY KEY (repository_id, name)
);
CREATE TABLE workflow_state (
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (repository_id, stage)
);
"""

_V2_SCHEMA = """
CREATE TABLE repository_files (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    relative_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE (repository_id, relative_path)
);
CREATE INDEX repository_files_kind_idx ON repository_files (repository_id, kind);
CREATE TABLE generated_reports (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    report_name TEXT NOT NULL,
    format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE (repository_id, report_name, format)
);
"""

_V3_SCHEMA = """
CREATE TABLE build_configurations (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    name TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX build_configurations_repository_idx
    ON build_configurations (repository_id, name);
CREATE TABLE build_discovery_runs (
    input_fingerprint TEXT PRIMARY KEY,
    build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
    build_fingerprint TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE compiler_invocations (
    id TEXT PRIMARY KEY,
    build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
    working_directory TEXT NOT NULL,
    source_path TEXT,
    payload TEXT NOT NULL
);
CREATE TABLE compilation_units (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
    source_file_id TEXT,
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX compilation_units_source_idx
    ON compilation_units (repository_id, source_file_id);
CREATE TABLE build_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_configuration_id TEXT NOT NULL REFERENCES build_configurations(id),
    sequence INTEGER NOT NULL,
    working_directory TEXT NOT NULL,
    classification TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (build_configuration_id, sequence)
);
"""

_V4_SCHEMA = """
CREATE TABLE input_artifacts (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    staleness_status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX input_artifacts_repository_idx
    ON input_artifacts (repository_id, artifact_type);
"""

_UNIT_PAYLOAD = """
{
  "id": "unit-1",
  "repository_id": "repository-1",
  "build_configuration_id": "build-1",
  "source_file_id": null,
  "fingerprint": "unit-fingerprint",
  "compiler_invocation": {
    "id": "invocation-1",
    "compiler_executable": "gcc",
    "launchers": [],
    "source": null,
    "object_file": null,
    "working_directory": "/repo",
    "raw_command": "gcc -c main.c",
    "raw_arguments": ["-c", "main.c"],
    "arguments": {},
    "parse_diagnostics": []
  }
}
"""

_ARTIFACT_PAYLOAD = """
{
  "id": "artifact-1",
  "repository_id": "repository-1",
  "artifact_type": "make_dry_run",
  "file_path": "/out/input/abc-make.txt",
  "source": "/tmp/make.txt",
  "command_used": null,
  "working_directory": "/repo",
  "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "creation_time": "2026-08-22T09:30:00+00:00",
  "validation_status": "valid",
  "validation_messages": [],
  "build_configuration_id": null,
  "staleness_status": "current"
}
"""


class MigrationTests(unittest.TestCase):
    def _snapshot(self, root: Path, version: int) -> Path:
        database = root / f"v{version}-index.sqlite"
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executescript(_BASE_SCHEMA)
        if version >= 2:
            connection.executescript(_V2_SCHEMA)
        if version >= 3:
            connection.execute(
                "ALTER TABLE diagnostics ADD COLUMN "
                "context_key TEXT NOT NULL DEFAULT 'general'"
            )
            connection.executescript(_V3_SCHEMA)
        if version >= 4:
            connection.executescript(_V4_SCHEMA)

        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO repositories (id, root, name, created_at) "
            "VALUES ('repository-1', '/repo', 'repo', ?)",
            (created_at,),
        )
        connection.execute(
            "INSERT INTO diagnostics (repository_id, code, severity, message, payload) "
            "VALUES ('repository-1', 'CI-COMP-001', 'warning', 'seeded', '{}')"
        )
        if version >= 3:
            connection.execute(
                "INSERT INTO build_configurations (id, repository_id, name, payload) "
                "VALUES ('build-1', 'repository-1', 'linux', '{}')"
            )
            connection.execute(
                "INSERT INTO compilation_units "
                "(id, repository_id, build_configuration_id, source_file_id, "
                " fingerprint, payload) "
                "VALUES ('unit-1', 'repository-1', 'build-1', NULL, "
                "        'unit-fingerprint', ?)",
                (_UNIT_PAYLOAD,),
            )
        if version >= 4:
            connection.execute(
                "INSERT INTO input_artifacts "
                "(id, repository_id, artifact_type, file_path, content_hash, "
                " validation_status, staleness_status, payload) "
                "VALUES ('artifact-1', 'repository-1', 'make_dry_run', "
                "        '/out/input/abc-make.txt', 'a', 'valid', 'current', ?)",
                (_ARTIFACT_PAYLOAD,),
            )
        connection.execute(
            "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        connection.commit()
        connection.close()
        return database

    def _migrated_storage(self, version: int):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = self._snapshot(Path(temporary.name), version)
        storage = SQLiteAnalysisStorage(database)
        storage.initialize()
        self.addCleanup(storage.close)
        return storage

    def test_migrates_v2_snapshot_to_current_schema(self) -> None:
        storage = self._migrated_storage(2)

        self.assertEqual(SCHEMA_VERSION, storage.schema_version())
        repository = storage.get_repository("repository-1")
        self.assertIsNotNone(repository)
        assert repository is not None
        self.assertEqual("/repo", repository.root)
        self.assertEqual((), storage.list_input_artifacts("repository-1"))
        self.assertEqual((), storage.list_compilation_units("repository-1"))

    def test_migrates_v3_snapshot_preserving_build_state(self) -> None:
        storage = self._migrated_storage(3)

        units = storage.list_compilation_units("repository-1")
        self.assertEqual(1, len(units))
        self.assertEqual("unit-1", units[0].id)
        self.assertEqual("gcc", units[0].compiler_invocation.compiler_executable)
        self.assertEqual((), storage.list_input_artifacts("repository-1"))

    def test_migrates_v4_snapshot_preserving_artifact_state(self) -> None:
        storage = self._migrated_storage(4)

        artifacts = storage.list_input_artifacts("repository-1")
        self.assertEqual(1, len(artifacts))
        self.assertEqual("artifact-1", artifacts[0].id)
        self.assertEqual("gcc", storage.list_compilation_units("repository-1")[0]
                           .compiler_invocation.compiler_executable)

    def test_seeded_diagnostic_keeps_general_context_after_migration(self) -> None:
        storage = self._migrated_storage(2)

        loaded = storage.list_diagnostics("repository-1")
        self.assertEqual(1, len(loaded))
        self.assertEqual("CI-COMP-001", loaded[0].code)
        self.assertIn("seeded", loaded[0].message)


if __name__ == "__main__":
    unittest.main()
