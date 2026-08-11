from __future__ import annotations

import json
from datetime import datetime
from enum import Enum

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    Recoverability,
    RelatedCommand,
)
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    BuildDiscoveryResult,
    CallRelationship,
    CapabilityStatus,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    EvidenceKind,
    FunctionSymbol,
    GlobalUsageRelationship,
    IncludeRelationship,
    IncludePath,
    InputArtifact,
    InputArtifactType,
    ArtifactValidationStatus,
    MacroDefinition,
    MacroSymbol,
    PathReference,
    RawBuildCommand,
    RelationshipEvidence,
    RelationshipResolution,
    SourceAnalysisResult,
    SourceAnalysisStatus,
    SourceLocation,
    SourceRelationship,
    SourceSymbol,
    StalenessStatus,
    TypeSymbol,
    VariableSymbol,
    Linkage,
)
from cintel.utilities.secrets import is_sensitive_name


def sanitized_json(value: object, configuration: BuildConfiguration) -> str:
    secret_values = _secret_values(configuration)

    def sanitize(item: object) -> object:
        if isinstance(item, dict):
            return {key: sanitize(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [sanitize(value) for value in item]
        if isinstance(item, str):
            return _redact_secret_values(item, secret_values)
        return item

    return json.dumps(sanitize(value), default=json_default, sort_keys=True)


def redact_text(value: str, configuration: BuildConfiguration) -> str:
    return _redact_secret_values(value, _secret_values(configuration))


def build_configuration_from_dict(data: dict) -> BuildConfiguration:
    return BuildConfiguration(
        id=data["id"],
        repository_id=data["repository_id"],
        name=data["name"],
        repository_root=data["repository_root"],
        makefile=data.get("makefile"),
        working_directory=data.get("working_directory"),
        target=data.get("target"),
        make_variables=tuple(tuple(item) for item in data.get("make_variables", ())),
        environment_overrides=tuple(
            tuple(item) for item in data.get("environment_overrides", ())
        ),
        build_input_hashes=tuple(
            tuple(item) for item in data.get("build_input_hashes", ())
        ),
        respect_make_timestamps=bool(data.get("respect_make_timestamps", False)),
    )


def build_result_from_dict(data: dict) -> BuildDiscoveryResult:
    return BuildDiscoveryResult(
        configuration=build_configuration_from_dict(data["configuration"]),
        make_arguments=tuple(data.get("make_arguments", ())),
        raw_output=data.get("raw_output", ""),
        raw_error=data.get("raw_error", ""),
        exit_code=int(data["exit_code"]),
        duration_seconds=float(data["duration_seconds"]),
        commands=tuple(
            RawBuildCommand(
                raw_content=item["raw_content"],
                working_directory=item["working_directory"],
                classification=item["classification"],
                parse_diagnostic=(
                    diagnostic_from_dict(item["parse_diagnostic"])
                    if item.get("parse_diagnostic")
                    else None
                ),
            )
            for item in data.get("commands", ())
        ),
        compiler_invocations=tuple(
            _compiler_invocation_from_dict(item)
            for item in data.get("compiler_invocations", ())
        ),
        compilation_units=tuple(
            compilation_unit_from_dict(item)
            for item in data.get("compilation_units", ())
        ),
        diagnostics=tuple(
            diagnostic_from_dict(item) for item in data.get("diagnostics", ())
        ),
        capabilities=tuple(
            _capability_from_dict(item) for item in data.get("capabilities", ())
        ),
        input_fingerprint=data["input_fingerprint"],
        build_fingerprint=data["build_fingerprint"],
        discovered_at=datetime.fromisoformat(data["discovered_at"]),
        compiler_versions=tuple(
            tuple(item) for item in data.get("compiler_versions", ())
        ),
        selected_source_files=tuple(data.get("selected_source_files", ())),
        excluded_source_files=tuple(data.get("excluded_source_files", ())),
        missing_source_files=tuple(data.get("missing_source_files", ())),
        from_cache=bool(data.get("from_cache", False)),
    )


def compilation_unit_from_dict(data: dict) -> CompilationUnit:
    return CompilationUnit(
        id=data["id"],
        repository_id=data["repository_id"],
        build_configuration_id=data["build_configuration_id"],
        source_file_id=data.get("source_file_id"),
        compiler_invocation=_compiler_invocation_from_dict(
            data["compiler_invocation"]
        ),
        fingerprint=data["fingerprint"],
    )


def json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _secret_values(configuration: BuildConfiguration) -> tuple[str, ...]:
    return tuple(
        value
        for name, value in (
            *configuration.make_variables,
            *configuration.environment_overrides,
        )
        if value and is_sensitive_name(name)
    )


def _redact_secret_values(value: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        value = value.replace(secret, "***REDACTED***")
    return value


def _path_reference_from_dict(data: dict | None) -> PathReference | None:
    return PathReference(**data) if data else None


def _required_path_reference(data: dict) -> PathReference:
    result = _path_reference_from_dict(data)
    if result is None:
        raise ValueError("Expected a path reference")
    return result


def diagnostic_from_dict(data: dict) -> Diagnostic:
    return Diagnostic(
        code=data["code"],
        severity=DiagnosticSeverity(data["severity"]),
        message=data["message"],
        technical_details=data.get("technical_details", ""),
        missing_capability=data.get("missing_capability"),
        recoverability=Recoverability(data.get("recoverability", "automatic")),
        suggested_actions=tuple(data.get("suggested_actions", ())),
        related_paths=tuple(data.get("related_paths", ())),
        related_commands=tuple(
            RelatedCommand(
                arguments=tuple(item["arguments"]),
                working_directory=item["working_directory"],
            )
            for item in data.get("related_commands", ())
        ),
        metadata=dict(data.get("metadata", {})),
    )


def _compiler_invocation_from_dict(data: dict) -> CompilerInvocation:
    arguments = data["arguments"]
    return CompilerInvocation(
        id=data["id"],
        compiler_executable=data["compiler_executable"],
        launchers=tuple(data.get("launchers", ())),
        source=_path_reference_from_dict(data.get("source")),
        object_file=_path_reference_from_dict(data.get("object_file")),
        working_directory=data["working_directory"],
        raw_command=data["raw_command"],
        raw_arguments=tuple(data.get("raw_arguments", ())),
        arguments=CompilerArgumentSet(
            include_paths=tuple(
                IncludePath(
                    path=_required_path_reference(item["path"]),
                    is_system=bool(item.get("is_system", False)),
                )
                for item in arguments.get("include_paths", ())
            ),
            defines=tuple(
                MacroDefinition(name=item["name"], value=item.get("value"))
                for item in arguments.get("defines", ())
            ),
            undefines=tuple(arguments.get("undefines", ())),
            forced_includes=tuple(
                _required_path_reference(item)
                for item in arguments.get("forced_includes", ())
            ),
            language_standard=arguments.get("language_standard"),
            optimization_flags=tuple(arguments.get("optimization_flags", ())),
            debug_flags=tuple(arguments.get("debug_flags", ())),
            warning_flags=tuple(arguments.get("warning_flags", ())),
            architecture_flags=tuple(arguments.get("architecture_flags", ())),
            dependency_flags=tuple(arguments.get("dependency_flags", ())),
            unclassified_arguments=tuple(
                arguments.get("unclassified_arguments", ())
            ),
        ),
        parse_diagnostics=tuple(
            diagnostic_from_dict(item) for item in data.get("parse_diagnostics", ())
        ),
    )


def _capability_from_dict(data: dict) -> AnalysisCapability:
    return AnalysisCapability(
        name=data["name"],
        status=CapabilityStatus(data["status"]),
        reason=data["reason"],
        evidence=tuple(data.get("evidence", ())),
    )


def input_artifact_from_dict(data: dict) -> InputArtifact:
    return InputArtifact(
        id=data["id"],
        repository_id=data["repository_id"],
        artifact_type=InputArtifactType(data["artifact_type"]),
        file_path=data["file_path"],
        source=data["source"],
        command_used=(
            tuple(data["command_used"]) if data.get("command_used") is not None else None
        ),
        working_directory=data.get("working_directory"),
        content_hash=data["content_hash"],
        creation_time=datetime.fromisoformat(data["creation_time"]),
        validation_status=ArtifactValidationStatus(data["validation_status"]),
        validation_messages=tuple(data.get("validation_messages", ())),
        build_configuration_id=data.get("build_configuration_id"),
        staleness_status=StalenessStatus(data["staleness_status"]),
    )


def source_analysis_from_parts(
    data: dict,
    symbols: tuple[SourceSymbol, ...],
    relationships: tuple[SourceRelationship, ...],
    diagnostics: tuple[Diagnostic, ...],
) -> SourceAnalysisResult:
    return SourceAnalysisResult(
        id=data["id"],
        repository_id=data["repository_id"],
        repository_file_id=data["repository_file_id"],
        compilation_unit_id=data.get("compilation_unit_id"),
        source_hash=data["source_hash"],
        analysis_fingerprint=data["analysis_fingerprint"],
        parser_name=data["parser_name"],
        parser_version=data["parser_version"],
        status=SourceAnalysisStatus(data["status"]),
        symbols=symbols,
        relationships=relationships,
        diagnostics=diagnostics,
        analyzed_at=datetime.fromisoformat(data["analyzed_at"]),
    )


def source_symbol_from_dict(kind: str, data: dict) -> SourceSymbol:
    common = {
        "id": data["id"],
        "name": data["name"],
        "location": _source_location_from_dict(data["location"]),
        "confidence": float(data.get("confidence", 1.0)),
        "evidence": tuple(
            _relationship_evidence_from_dict(item)
            for item in data.get("evidence", ())
        ),
    }
    if kind == "function":
        return FunctionSymbol(
            **common,
            is_definition=bool(data["is_definition"]),
            linkage=Linkage(data["linkage"]),
            return_type=data.get("return_type"),
            parameters=tuple(data.get("parameters", ())),
        )
    if kind == "variable":
        return VariableSymbol(
            **common,
            type_spelling=data.get("type_spelling"),
            linkage=Linkage(data["linkage"]),
            is_definition=bool(data["is_definition"]),
        )
    if kind == "type":
        return TypeSymbol(
            **common,
            type_kind=data["type_kind"],
            is_definition=bool(data["is_definition"]),
            underlying_type=data.get("underlying_type"),
        )
    if kind == "macro":
        return MacroSymbol(
            **common,
            replacement=data.get("replacement"),
            is_function_like=bool(data.get("is_function_like", False)),
            parameters=tuple(data.get("parameters", ())),
        )
    raise ValueError(f"Unsupported source symbol kind: {kind}")


def source_relationship_from_dict(kind: str, data: dict) -> SourceRelationship:
    evidence = tuple(
        _relationship_evidence_from_dict(item) for item in data.get("evidence", ())
    )
    if kind == "include":
        return IncludeRelationship(
            id=data["id"],
            source_file_id=data["source_file_id"],
            included_spelling=data["included_spelling"],
            resolved_file_id=data.get("resolved_file_id"),
            evidence=evidence,
            confidence=float(data["confidence"]),
        )
    if kind == "call":
        return CallRelationship(
            id=data["id"],
            caller_id=data["caller_id"],
            callee_id=data.get("callee_id"),
            callee_spelling=data["callee_spelling"],
            resolution=RelationshipResolution(data["resolution"]),
            evidence=evidence,
            confidence=float(data["confidence"]),
        )
    if kind == "global_usage":
        return GlobalUsageRelationship(
            id=data["id"],
            function_id=data["function_id"],
            variable_id=data.get("variable_id"),
            variable_spelling=data["variable_spelling"],
            evidence=evidence,
            confidence=float(data["confidence"]),
        )
    raise ValueError(f"Unsupported source relationship kind: {kind}")


def _source_location_from_dict(data: dict) -> SourceLocation:
    return SourceLocation(
        path=data["path"],
        line=int(data["line"]),
        column=int(data.get("column", 1)),
        end_line=int(data["end_line"]) if data.get("end_line") is not None else None,
        end_column=(
            int(data["end_column"]) if data.get("end_column") is not None else None
        ),
    )


def _relationship_evidence_from_dict(data: dict) -> RelationshipEvidence:
    return RelationshipEvidence(
        kind=EvidenceKind(data["kind"]),
        description=data["description"],
        location=(
            _source_location_from_dict(data["location"])
            if data.get("location")
            else None
        ),
        provenance=data.get("provenance"),
    )
