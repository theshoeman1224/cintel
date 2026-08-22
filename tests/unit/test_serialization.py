import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.storage import SQLiteAnalysisStorage
from cintel.adapters.storage.serialization import (
    build_configuration_from_dict,
    build_result_from_dict,
    compilation_unit_from_dict,
    input_artifact_from_dict,
    json_default,
    sanitized_json,
    source_relationship_from_dict,
    source_symbol_from_dict,
)
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    Recoverability,
    RelatedCommand,
)
from cintel.domain.models import (
    ArtifactValidationStatus,
    BuildConfiguration,
    BuildDiscoveryResult,
    CallRelationship,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    EvidenceKind,
    FunctionSymbol,
    GlobalUsageRelationship,
    IncludeRelationship,
    InputArtifact,
    InputArtifactType,
    IncludePath,
    Linkage,
    MacroSymbol,
    PathReference,
    Repository,
    RelationshipEvidence,
    RelationshipResolution,
    SourceLocation,
    StalenessStatus,
    TypeSymbol,
    VariableSymbol,
)


def _location() -> SourceLocation:
    return SourceLocation(path="src/main.c", line=4, column=1, end_line=6, end_column=20)


def _evidence() -> tuple[RelationshipEvidence, ...]:
    return (
        RelationshipEvidence(
            kind=EvidenceKind.HEURISTIC_RESULT,
            description="Conservative extraction.",
            location=_location(),
            provenance="conservative-c",
        ),
    )


def _wire(value):
    return json.loads(json.dumps(asdict(value), default=json_default, sort_keys=True))


class SymbolSerializationTests(unittest.TestCase):
    def _round_trip(self, symbol):
        return source_symbol_from_dict(_kind(symbol), _wire(symbol))

    def test_function_symbol_round_trips(self) -> None:
        symbol = FunctionSymbol(
            id="symbol-1",
            name="helper",
            location=_location(),
            is_definition=True,
            linkage=Linkage.INTERNAL,
            return_type="int",
            parameters=("int", "char *"),
            confidence=0.9,
            evidence=_evidence(),
        )
        restored = self._round_trip(symbol)
        self.assertEqual(symbol, restored)

    def test_variable_symbol_round_trips(self) -> None:
        symbol = VariableSymbol(
            id="symbol-2",
            name="counter",
            location=_location(),
            type_spelling="unsigned long",
            linkage=Linkage.EXTERNAL,
            is_definition=False,
            confidence=0.8,
            evidence=_evidence(),
        )
        self.assertEqual(symbol, self._round_trip(symbol))

    def test_type_symbol_round_trips(self) -> None:
        symbol = TypeSymbol(
            id="symbol-3",
            name="router_state",
            type_kind="typedef",
            location=_location(),
            is_definition=True,
            confidence=0.85,
            underlying_type="struct router",
            evidence=_evidence(),
        )
        self.assertEqual(symbol, self._round_trip(symbol))

    def test_macro_symbol_round_trips(self) -> None:
        symbol = MacroSymbol(
            id="symbol-4",
            name="MAX_SENSORS",
            location=_location(),
            replacement="( 8 )",
            confidence=1.0,
            is_function_like=False,
            parameters=(),
            evidence=_evidence(),
        )
        self.assertEqual(symbol, self._round_trip(symbol))


def _kind(symbol):
    if isinstance(symbol, FunctionSymbol):
        return "function"
    if isinstance(symbol, VariableSymbol):
        return "variable"
    if isinstance(symbol, TypeSymbol):
        return "type"
    return "macro"


class RelationshipSerializationTests(unittest.TestCase):
    def test_include_relationship_round_trips(self) -> None:
        relationship = IncludeRelationship(
            id="rel-1",
            source_file_id="file-1",
            included_spelling="cintel_fixture/router.h",
            resolved_file_id=None,
            evidence=_evidence(),
            confidence=1.0,
        )
        restored = source_relationship_from_dict("include", _wire(relationship))
        self.assertEqual(relationship, restored)

    def test_call_relationship_round_trips_even_though_no_parser_writes_it(self) -> None:
        relationship = CallRelationship(
            id="rel-2",
            caller_id="caller-symbol",
            callee_id=None,
            callee_spelling="checksum_block",
            resolution=RelationshipResolution.POSSIBLE_INDIRECT,
            evidence=_evidence(),
            confidence=0.7,
        )
        restored = source_relationship_from_dict("call", _wire(relationship))
        self.assertEqual(relationship, restored)

    def test_global_usage_relationship_round_trips_even_though_no_parser_writes_it(
        self,
    ) -> None:
        relationship = GlobalUsageRelationship(
            id="rel-3",
            function_id="caller-symbol",
            variable_id=None,
            variable_spelling="g_router_state",
            evidence=_evidence(),
            confidence=0.75,
        )
        restored = source_relationship_from_dict("global_usage", _wire(relationship))
        self.assertEqual(relationship, restored)


class BuildPayloadSerializationTests(unittest.TestCase):
    def _configuration(self, **overrides) -> BuildConfiguration:
        values = {
            "id": "build-1",
            "repository_id": "repository-1",
            "name": "linux",
            "repository_root": "/repo",
            "makefile": "/repo/Makefile",
            "working_directory": "/repo",
            "target": "all",
            "make_variables": (("MODE", "debug"),),
            "environment_overrides": (("CFLAGS", "-O2"),),
            "build_input_hashes": (("Makefile", "a" * 64),),
            "respect_make_timestamps": True,
        }
        values.update(overrides)
        return BuildConfiguration(**values)

    def test_build_configuration_round_trips(self) -> None:
        configuration = self._configuration()
        payload = json.dumps(asdict(configuration), default=json_default, sort_keys=True)
        restored = build_configuration_from_dict(json.loads(payload))
        self.assertEqual(configuration, restored)

    def test_sanitized_payload_redacts_secret_values_before_storage(self) -> None:
        configuration = self._configuration(
            make_variables=(("MODE", "debug"), ("API_TOKEN", "super-secret")),
            environment_overrides=(("API_KEY", "hunter2"),),
        )
        result = BuildDiscoveryResult(
            configuration=configuration,
            make_arguments=("make", "-n"),
            raw_output="make -n API_TOKEN=super-secret",
            raw_error="",
            exit_code=0,
            duration_seconds=0.5,
            commands=(),
            compiler_invocations=(),
            compilation_units=(),
            diagnostics=(),
            capabilities=(),
            input_fingerprint="in-fp",
            build_fingerprint="build-fp",
            discovered_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        payload = sanitized_json(asdict(result), configuration)

        self.assertNotIn("super-secret", payload)
        self.assertNotIn("hunter2", payload)
        self.assertIn("***REDACTED***", payload)
        restored = build_result_from_dict(json.loads(payload))
        self.assertEqual(result.exit_code, restored.exit_code)
        self.assertEqual(
            "***REDACTED***",
            dict(restored.configuration.make_variables)["API_TOKEN"],
        )

    def test_compilation_unit_with_invocation_round_trips(self) -> None:
        invocation = CompilerInvocation(
            id="invocation-1",
            compiler_executable="arm-none-eabi-gcc",
            launchers=("ccache",),
            source=PathReference(original="../src/main.c", absolute="/repo/src/main.c", repository_relative="src/main.c"),
            object_file=PathReference(original="main.o", absolute="/repo/build/main.o", repository_relative=None),
            working_directory="/repo/build",
            raw_command="ccache arm-none-eabi-gcc -c ../src/main.c",
            raw_arguments=("-c", "../src/main.c"),
            arguments=CompilerArgumentSet(
                include_paths=(
                    IncludePath(
                        path=PathReference(
                            original="inc", absolute="/repo/inc", repository_relative="inc"
                        ),
                        is_system=True,
                    ),
                )
            ),
        )
        unit = CompilationUnit(
            id="unit-1",
            repository_id="repository-1",
            build_configuration_id="build-1",
            source_file_id="file-1",
            compiler_invocation=invocation,
            fingerprint="fp",
        )
        payload = json.dumps(asdict(unit), default=json_default, sort_keys=True)
        restored = compilation_unit_from_dict(json.loads(payload))
        self.assertEqual(unit, restored)


class InputArtifactSerializationTests(unittest.TestCase):
    def test_input_artifact_round_trips(self) -> None:
        artifact = InputArtifact(
            id="artifact-1",
            repository_id="repository-1",
            artifact_type=InputArtifactType.PREPROCESSED_SOURCE,
            file_path="/out/input/abc-application.i",
            source="/tmp/application.i",
            command_used=("gcc", "-E", "application.c"),
            working_directory="/repo",
            content_hash="b" * 64,
            creation_time=datetime(2026, 8, 22, 9, 30, tzinfo=timezone.utc),
            validation_status=ArtifactValidationStatus.VALID,
            validation_messages=("Validated preprocessed_source structure.",),
            build_configuration_id=None,
            staleness_status=StalenessStatus.CURRENT,
        )
        payload = json.dumps(asdict(artifact), default=json_default, sort_keys=True)
        restored = input_artifact_from_dict(json.loads(payload))
        self.assertEqual(artifact, restored)


class DiagnosticPersistenceTests(unittest.TestCase):
    def test_diagnostic_with_commands_and_metadata_survives_storage_round_trip(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteAnalysisStorage(Path(directory) / "index.sqlite")
            storage.initialize()
            storage.save_repository(
                Repository(
                    id="repository-1",
                    root="/repo",
                    name="repo",
                    created_at=datetime.now(timezone.utc),
                )
            )
            original = Diagnostic(
                code="CI-BUILD-001",
                severity=DiagnosticSeverity.ERROR,
                message="GNU Make could not be executed.",
                technical_details="exit 127",
                missing_capability="make_build_discovery",
                recoverability=Recoverability.USER_ACTION,
                suggested_actions=("Install GNU Make.", "Or import saved output."),
                related_paths=("/repo/Makefile",),
                related_commands=(
                    RelatedCommand(arguments=("make", "-n", "-B"), working_directory="/repo"),
                    RelatedCommand(arguments=("make", "--version"), working_directory="/repo"),
                ),
                metadata={"line": "12", "column": "3"},
            )

            storage.save_diagnostics("repository-1", (original,), context="build:build-1")
            loaded = storage.list_diagnostics("repository-1")

            self.assertEqual((original,), loaded)
            prefixed = storage.list_diagnostics("repository-1", context_prefix="build:")
            self.assertEqual((original,), prefixed)
            other_context = storage.list_diagnostics(
                "repository-1", context_prefix="parse:"
            )
            self.assertEqual((), other_context)
            storage.close()


if __name__ == "__main__":
    unittest.main()
