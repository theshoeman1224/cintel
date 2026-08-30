import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.parsing import ConservativeCSourceParser
from cintel.adapters.storage import SCHEMA_VERSION, SQLiteAnalysisStorage
from cintel.domain.diagnostics import Diagnostic, DiagnosticSeverity
from cintel.domain.models import (
    AnalysisCapability,
    ArtifactValidationStatus,
    BuildConfiguration,
    BuildDiscoveryResult,
    CallRelationship,
    CapabilityStatus,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    FileKind,
    FunctionSymbol,
    InputArtifact,
    InputArtifactType,
    RelationshipResolution,
    Repository,
    RepositoryFile,
    replace_fields,
    PathReference,
    StalenessStatus,
    WorkflowState,
    WorkflowStatus,
)


class SQLiteStorageTests(unittest.TestCase):
    def test_initializes_and_persists_phase_one_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteAnalysisStorage(Path(directory) / "index.sqlite")
            storage.initialize()
            repository = Repository(
                id="repository-1",
                root="/repo",
                name="repo",
                created_at=datetime.now(timezone.utc),
            )
            storage.save_repository(repository)
            storage.save_diagnostics(
                repository.id,
                (
                    Diagnostic(
                        code="CI-COMP-001",
                        severity=DiagnosticSeverity.WARNING,
                        message="Compiler unavailable",
                    ),
                ),
            )
            storage.save_capabilities(
                repository.id,
                (
                    AnalysisCapability(
                        name="gcc",
                        status=CapabilityStatus.UNAVAILABLE,
                        reason="Not found",
                    ),
                ),
            )

            self.assertEqual(SCHEMA_VERSION, storage.schema_version())
            self.assertEqual(repository, storage.get_repository(repository.id))
            repository_file = RepositoryFile(
                id="file-1",
                repository_id=repository.id,
                relative_path="main.c",
                absolute_path="/repo/main.c",
                kind=FileKind.C_SOURCE,
                size=10,
                modified_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
            storage.replace_repository_files(repository.id, (repository_file,))
            self.assertEqual(
                (repository_file,), storage.list_repository_files(repository.id)
            )
            storage.replace_repository_files(repository.id, ())
            self.assertEqual((), storage.list_repository_files(repository.id))
            storage.close()

    def test_migrates_an_existing_v1_database_to_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "index.sqlite"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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
                INSERT INTO schema_metadata (key, value)
                VALUES ('schema_version', '1');
                """
            )
            connection.commit()
            connection.close()

            storage = SQLiteAnalysisStorage(database)
            storage.initialize()

            self.assertEqual(SCHEMA_VERSION, storage.schema_version())
            self.assertEqual((), storage.list_repository_files("repository-1"))
            connection = sqlite3.connect(database)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            connection.close()
            self.assertTrue(
                {
                    "source_analysis_runs",
                    "source_symbols",
                    "source_relationships",
                }.issubset(tables)
            )
            storage.close()

    def test_persists_input_artifacts_and_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteAnalysisStorage(Path(directory) / "index.sqlite")
            storage.initialize()
            repository = Repository(
                id="repository-1",
                root="/repo",
                name="repo",
                created_at=datetime.now(timezone.utc),
            )
            storage.save_repository(repository)
            artifact = InputArtifact(
                id="artifact-1",
                repository_id=repository.id,
                artifact_type=InputArtifactType.MAKE_DRY_RUN,
                file_path="/input/make.txt",
                source="/source/make.txt",
                command_used=("make", "-n"),
                working_directory="/repo",
                content_hash="a" * 64,
                creation_time=datetime.now(timezone.utc),
                validation_status=ArtifactValidationStatus.VALID,
                validation_messages=("valid",),
                build_configuration_id="build-1",
                staleness_status=StalenessStatus.CURRENT,
            )
            state = WorkflowState(
                repository_id=repository.id,
                stage="input_validation",
                status=WorkflowStatus.COMPLETED,
                updated_at=datetime.now(timezone.utc),
                details=(("artifact", artifact.id),),
            )
            storage.save_input_artifact(artifact)
            storage.save_workflow_state(state)

            self.assertEqual((artifact,), storage.list_input_artifacts(repository.id))
            self.assertEqual((state,), storage.list_workflow_states(repository.id))
            storage.close()

    def test_replaces_and_queries_source_analysis_for_file_and_compilation_unit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.c"
            source.write_text(
                '#include "project.h"\n'
                "#define ENABLED 1\n"
                "#if ENABLED\n"
                "extern int shared_value;\n"
                "#endif\n"
                "static int helper(int value) { return value + 1; }\n",
                encoding="utf-8",
            )
            storage = SQLiteAnalysisStorage(root / "index.sqlite")
            storage.initialize()
            repository = Repository(
                id="repository-1",
                root=str(root),
                name="fixture",
                created_at=datetime.now(timezone.utc),
            )
            repository_file = RepositoryFile(
                id="file-1",
                repository_id=repository.id,
                relative_path="main.c",
                absolute_path=str(source),
                kind=FileKind.C_SOURCE,
                size=source.stat().st_size,
                modified_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
            storage.save_repository(repository)
            storage.replace_repository_files(repository.id, (repository_file,))
            configuration = BuildConfiguration(
                id="build-1",
                repository_id=repository.id,
                name="debug",
                repository_root=str(root),
                working_directory=str(root),
            )
            invocation = CompilerInvocation(
                id="invocation-1",
                compiler_executable="gcc",
                launchers=(),
                source=PathReference(
                    original="main.c",
                    absolute=str(source),
                    repository_relative="main.c",
                ),
                object_file=None,
                working_directory=str(root),
                raw_command="gcc -c main.c",
                raw_arguments=("-c", "main.c"),
                arguments=CompilerArgumentSet(unclassified_arguments=("-c",)),
            )
            compilation_unit = CompilationUnit(
                id="unit-1",
                repository_id=repository.id,
                build_configuration_id=configuration.id,
                source_file_id=repository_file.id,
                compiler_invocation=invocation,
                fingerprint="unit-fingerprint",
            )
            storage.save_build_discovery(
                BuildDiscoveryResult(
                    configuration=configuration,
                    make_arguments=("make", "-n"),
                    raw_output="gcc -c main.c",
                    raw_error="",
                    exit_code=0,
                    duration_seconds=0.01,
                    commands=(),
                    compiler_invocations=(invocation,),
                    compilation_units=(compilation_unit,),
                    diagnostics=(),
                    capabilities=(),
                    input_fingerprint="input-fingerprint",
                    build_fingerprint="build-fingerprint",
                    discovered_at=datetime.now(timezone.utc),
                )
            )
            parser = ConservativeCSourceParser()
            unconfigured = parser.parse(repository_file, None)
            configured = parser.parse(repository_file, compilation_unit)
            storage.replace_source_analysis(unconfigured)
            storage.replace_source_analysis(configured)

            file_results = storage.list_source_analyses_for_file(repository_file.id)
            configured_result = storage.get_source_analysis_for_compilation_unit(
                compilation_unit.id
            )

            self.assertEqual(2, len(file_results))
            self.assertIsNotNone(configured_result)
            assert configured_result is not None
            self.assertEqual(configured.id, configured_result.id)
            self.assertEqual(
                {item.id for item in configured.symbols},
                {item.id for item in configured_result.symbols},
            )
            self.assertEqual(
                {item.id for item in configured.relationships},
                {item.id for item in configured_result.relationships},
            )
            self.assertEqual(configured.diagnostics, configured_result.diagnostics)

            replacement = replace(configured, symbols=configured.symbols[:1])
            storage.replace_source_analysis(replacement)
            replaced = storage.get_source_analysis_for_compilation_unit(
                compilation_unit.id
            )
            assert replaced is not None
            self.assertEqual(1, len(replaced.symbols))
            storage.close()

    def test_find_symbols_and_call_edges_use_projection_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.c"
            source.write_text(
                '#include "project.h"\n'
                "#define ENABLED 1\n"
                "static int helper(int value) { return value + 1; }\n"
                "int run(int input) { return helper(input); }\n",
                encoding="utf-8",
            )
            storage = SQLiteAnalysisStorage(root / "index.sqlite")
            storage.initialize()
            repository = Repository(
                id="repository-1",
                root=str(root),
                name="fixture",
                created_at=datetime.now(timezone.utc),
            )
            repository_file = RepositoryFile(
                id="file-1",
                repository_id=repository.id,
                relative_path="main.c",
                absolute_path=str(source),
                kind=FileKind.C_SOURCE,
                size=source.stat().st_size,
                modified_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
            storage.save_repository(repository)
            storage.replace_repository_files(repository.id, (repository_file,))
            parsed = ConservativeCSourceParser().parse(repository_file, None)
            symbols_by_name = {
                item.name: item
                for item in parsed.symbols
                if isinstance(item, FunctionSymbol)
            }
            unresolved_call = next(
                item
                for item in parsed.relationships
                if isinstance(item, CallRelationship)
                and item.callee_spelling == "helper"
            )
            resolved_call = replace_fields(
                unresolved_call,
                callee_id=symbols_by_name["helper"].id,
                resolution=RelationshipResolution.CONFIRMED_DIRECT,
            )
            result = replace_fields(parsed, relationships=(resolved_call,))
            storage.replace_source_analysis(result)

            functions = storage.find_symbols("repository-1", kind="function")
            self.assertEqual(
                {"helper", "run"}, {item.symbol.name for item in functions}
            )
            helper_occurrences = storage.find_symbols(
                "repository-1", kind="function", name="helper"
            )
            self.assertEqual(1, len(helper_occurrences))
            helper = helper_occurrences[0]
            self.assertEqual("file-1", helper.repository_file_id)
            self.assertEqual("repository-1", helper.repository_id)
            self.assertIsNone(helper.compilation_unit_id)

            edges = storage.find_call_edges(
                "repository-1", callee_spelling="helper"
            )
            self.assertEqual(1, len(edges))
            edge = edges[0]
            self.assertEqual("helper", edge.call.callee_spelling)
            self.assertIsNotNone(edge.call.callee_id)
            self.assertEqual(edge.analysis_id, result.id)
            self.assertEqual("file-1", edge.repository_file_id)

            callers = storage.get_symbols_by_ids(
                "repository-1", (edge.call.caller_id,)
            )
            self.assertEqual(1, len(callers))
            self.assertEqual("run", callers[0].symbol.name)

            callee_ids = (edge.call.callee_id,)
            self.assertEqual(1, len(storage.find_call_edges("repository-1", callee_ids=callee_ids)))
            self.assertEqual(
                1, len(storage.find_call_edges("repository-1", caller_ids=(edge.call.caller_id,)))
            )
            self.assertEqual(
                (), storage.find_call_edges("repository-1", caller_ids=("missing",))
            )
            self.assertEqual((), storage.find_call_edges("repository-1", callee_ids=()))
            self.assertEqual((), storage.get_symbols_by_ids("repository-1", ()))

            macros = storage.find_symbols("repository-1", kind="macro")
            self.assertEqual({"ENABLED"}, {item.symbol.name for item in macros})
            self.assertEqual(
                (), storage.find_symbols("repository-1", kind="function", name="absent")
            )
            storage.close()
