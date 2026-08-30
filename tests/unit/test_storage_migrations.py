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

_V5_SCHEMA = """
CREATE TABLE source_analysis_runs (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    repository_file_id TEXT NOT NULL REFERENCES repository_files(id)
        ON DELETE CASCADE,
    compilation_unit_id TEXT REFERENCES compilation_units(id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL,
    analysis_fingerprint TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX source_analysis_file_idx
    ON source_analysis_runs (repository_file_id, compilation_unit_id);
CREATE UNIQUE INDEX source_analysis_unit_idx
    ON source_analysis_runs (compilation_unit_id)
    WHERE compilation_unit_id IS NOT NULL;
CREATE TABLE source_symbols (
    analysis_id TEXT NOT NULL REFERENCES source_analysis_runs(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE INDEX source_symbols_name_idx ON source_symbols (name, kind);
CREATE TABLE source_relationships (
    analysis_id TEXT NOT NULL REFERENCES source_analysis_runs(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (analysis_id, id)
);
CREATE INDEX source_relationships_kind_idx ON source_relationships (kind);
"""

_FUNCTION_PAYLOAD = """
{
  "id": "function-1",
  "name": "helper",
  "location": {"path": "main.c", "line": 3, "column": 1},
  "is_definition": true,
  "linkage": "external",
  "return_type": "int",
  "parameters": ["int"],
  "confidence": 1.0,
  "evidence": []
}
"""

_MACRO_PAYLOAD = """
{
  "id": "macro-1",
  "name": "ENABLED",
  "location": {"path": "main.c", "line": 2, "column": 1},
  "replacement": "1",
  "confidence": 1.0,
  "is_function_like": false,
  "parameters": [],
  "evidence": []
}
"""

_CALL_PAYLOAD = """
{
  "id": "call-1",
  "caller_id": "function-1",
  "callee_id": "function-2",
  "callee_spelling": "helper",
  "resolution": "confirmed_direct",
  "evidence": [],
  "confidence": 1.0
}
"""

_GLOBAL_USAGE_PAYLOAD = """
{
  "id": "usage-1",
  "function_id": "function-1",
  "variable_id": "variable-1",
  "variable_spelling": "shared_value",
  "evidence": [],
  "confidence": 1.0
}
"""

_INCLUDE_PAYLOAD = """
{
  "id": "include-1",
  "source_file_id": "file-1",
  "included_spelling": "project.h",
  "resolved_file_id": null,
  "evidence": [],
  "confidence": 1.0
}
"""

_ANALYSIS_PAYLOAD = """
{
  "id": "analysis-1",
  "repository_id": "repository-1",
  "repository_file_id": "file-1",
  "compilation_unit_id": null,
  "source_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "analysis_fingerprint": "analysis-fingerprint",
  "parser_name": "conservative",
  "parser_version": "1",
  "status": "completed",
  "analyzed_at": "2026-08-22T09:30:00+00:00"
}
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
        if version >= 5:
            connection.executescript(_V5_SCHEMA)

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
        if version >= 5:
            connection.execute(
                "INSERT INTO repository_files "
                "(id, repository_id, relative_path, absolute_path, kind, size, "
                " modified_at, content_sha256) "
                "VALUES ('file-1', 'repository-1', 'main.c', '/repo/main.c', "
                "        'c_source', 10, ?, 'b" + "b" * 63 + "')",
                (created_at,),
            )
            connection.execute(
                "INSERT INTO source_analysis_runs "
                "(id, repository_id, repository_file_id, compilation_unit_id, "
                " source_hash, analysis_fingerprint, parser_name, parser_version, "
                " status, analyzed_at, payload) "
                "VALUES ('analysis-1', 'repository-1', 'file-1', NULL, "
                "        'c', 'analysis-fingerprint', 'conservative', '1', "
                "        'completed', '2026-08-22T09:30:00+00:00', ?)",
                (_ANALYSIS_PAYLOAD,),
            )
            connection.execute(
                "INSERT INTO source_symbols (analysis_id, id, kind, name, payload) "
                "VALUES ('analysis-1', 'function-1', 'function', 'helper', ?)",
                (_FUNCTION_PAYLOAD,),
            )
            connection.execute(
                "INSERT INTO source_symbols (analysis_id, id, kind, name, payload) "
                "VALUES ('analysis-1', 'macro-1', 'macro', 'ENABLED', ?)",
                (_MACRO_PAYLOAD,),
            )
            connection.execute(
                "INSERT INTO source_relationships "
                "(analysis_id, id, kind, payload) "
                "VALUES ('analysis-1', 'call-1', 'call', ?)",
                (_CALL_PAYLOAD,),
            )
            connection.execute(
                "INSERT INTO source_relationships "
                "(analysis_id, id, kind, payload) "
                "VALUES ('analysis-1', 'usage-1', 'global_usage', ?)",
                (_GLOBAL_USAGE_PAYLOAD,),
            )
            connection.execute(
                "INSERT INTO source_relationships "
                "(analysis_id, id, kind, payload) "
                "VALUES ('analysis-1', 'include-1', 'include', ?)",
                (_INCLUDE_PAYLOAD,),
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

    def test_migrates_v5_snapshot_backfilling_query_projections(self) -> None:
        storage = self._migrated_storage(5)

        self.assertEqual(SCHEMA_VERSION, storage.schema_version())

        symbols = storage.find_symbols("repository-1")
        self.assertEqual(2, len(symbols))
        self.assertEqual({"helper", "ENABLED"}, {o.symbol.name for o in symbols})

        functions = storage.find_symbols("repository-1", kind="function", name="helper")
        self.assertEqual(1, len(functions))
        helper = functions[0]
        self.assertEqual("helper", helper.symbol.name)
        self.assertEqual("file-1", helper.repository_file_id)
        self.assertEqual("analysis-1", helper.analysis_id)
        self.assertIsNone(helper.compilation_unit_id)
        assert helper.symbol.is_definition is True

        resolved = storage.get_symbols_by_ids("repository-1", ("function-1",))
        self.assertEqual(1, len(resolved))
        self.assertEqual("helper", resolved[0].symbol.name)
        self.assertEqual((), storage.get_symbols_by_ids("repository-1", ()))

        edges = storage.find_call_edges("repository-1", callee_spelling="helper")
        self.assertEqual(1, len(edges))
        edge = edges[0]
        self.assertEqual("function-1", edge.call.caller_id)
        self.assertEqual("function-2", edge.call.callee_id)
        self.assertEqual("file-1", edge.repository_file_id)
        by_caller = storage.find_call_edges("repository-1", caller_ids=("function-1",))
        self.assertEqual(1, len(by_caller))
        self.assertEqual((), storage.find_call_edges("repository-1", callee_ids=()))

    def test_seeded_diagnostic_keeps_general_context_after_migration(self) -> None:
        storage = self._migrated_storage(2)

        loaded = storage.list_diagnostics("repository-1")
        self.assertEqual(1, len(loaded))
        self.assertEqual("CI-COMP-001", loaded[0].code)
        self.assertIn("seeded", loaded[0].message)


if __name__ == "__main__":
    unittest.main()
