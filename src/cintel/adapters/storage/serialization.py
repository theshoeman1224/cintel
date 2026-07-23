from __future__ import annotations

import json
import re
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
    CapabilityStatus,
    CompilationUnit,
    CompilerArgumentSet,
    CompilerInvocation,
    IncludePath,
    MacroDefinition,
    PathReference,
    RawBuildCommand,
)

_SECRET_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH)(?:_|$)",
    re.IGNORECASE,
)


def sanitized_json(value: object, configuration: BuildConfiguration) -> str:
    secret_values = tuple(
        item_value
        for name, item_value in (
            *configuration.make_variables,
            *configuration.environment_overrides,
        )
        if item_value and _SECRET_NAME.search(name)
    )

    def sanitize(item: object) -> object:
        if isinstance(item, dict):
            return {key: sanitize(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [sanitize(value) for value in item]
        if isinstance(item, str):
            for secret in secret_values:
                item = item.replace(secret, "***REDACTED***")
            return item
        return item

    return json.dumps(sanitize(value), default=_json_default, sort_keys=True)


def redact_text(value: str, configuration: BuildConfiguration) -> str:
    for name, secret in (
        *configuration.make_variables,
        *configuration.environment_overrides,
    ):
        if secret and _SECRET_NAME.search(name):
            value = value.replace(secret, "***REDACTED***")
    return value


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
                    _diagnostic_from_dict(item["parse_diagnostic"])
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
            _diagnostic_from_dict(item) for item in data.get("diagnostics", ())
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


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _path_reference_from_dict(data: dict | None) -> PathReference | None:
    return PathReference(**data) if data else None


def _required_path_reference(data: dict) -> PathReference:
    result = _path_reference_from_dict(data)
    if result is None:
        raise ValueError("Expected a path reference")
    return result


def _diagnostic_from_dict(data: dict) -> Diagnostic:
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
            _diagnostic_from_dict(item) for item in data.get("parse_diagnostics", ())
        ),
    )


def _capability_from_dict(data: dict) -> AnalysisCapability:
    return AnalysisCapability(
        name=data["name"],
        status=CapabilityStatus(data["status"]),
        reason=data["reason"],
        evidence=tuple(data.get("evidence", ())),
    )
