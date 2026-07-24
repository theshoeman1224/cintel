from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from cintel.domain.models import InputArtifactType

_COMPILER_COMMAND = re.compile(
    r"(?:^|\s)(?:[\w.+-]*gcc|cc|clang)(?:\s|$).*?(?:\s-c\s|\s-o\s)",
    re.MULTILINE | re.DOTALL,
)
_C_CONTENT = re.compile(r"(?:#\s*\d+\s+\"|\b(?:int|void|struct|enum|typedef)\b)")


def validate_artifact(
    artifact_type: InputArtifactType, text: str, repository_root: Path
) -> tuple[bool, tuple[str, ...]]:
    if not text.strip():
        return False, ("Input file is empty.",)
    validator, expected_content = _VALIDATORS[artifact_type]
    if not validator(text):
        return False, (f"Input does not contain {expected_content}.",)

    messages = [f"Validated {artifact_type.value} structure."]
    if artifact_type in {InputArtifactType.MAKE_DRY_RUN, InputArtifactType.BUILD_LOG}:
        repository_names = _repository_source_names(repository_root)
        if repository_names and not any(name in text for name in repository_names):
            messages.append(
                "Warning: no selected repository source filename was recognized in the input."
            )
    return True, tuple(messages)


def _has_make_output(value: str) -> bool:
    return bool(_COMPILER_COMMAND.search(value) or "make: ***" in value)


def _has_compiler_command(value: str) -> bool:
    return bool(_COMPILER_COMMAND.search(value))


def _has_file_list(value: str) -> bool:
    return any(
        line.strip().endswith((".c", ".h", "Makefile", ".mk"))
        for line in value.splitlines()
    )


def _has_dependency_rule(value: str) -> bool:
    return ":" in value and any(
        token.endswith((".h", ".c")) for token in value.split()
    )


def _has_preprocessed_c(value: str) -> bool:
    return bool(_C_CONTENT.search(value))


def _has_macros(value: str) -> bool:
    return any(line.lstrip().startswith("#define ") for line in value.splitlines())


def _repository_source_names(repository_root: Path) -> set[str]:
    return {
        path.name
        for path in repository_root.rglob("*")
        if path.is_file() and path.suffix in {".c", ".h", ".mk"}
    }


_VALIDATORS: dict[InputArtifactType, tuple[Callable[[str], bool], str]] = {
    InputArtifactType.MAKE_DRY_RUN: (
        _has_make_output,
        "recognizable compiler commands or a clear Make failure",
    ),
    InputArtifactType.BUILD_LOG: (_has_compiler_command, "recognizable compiler commands"),
    InputArtifactType.FILE_LIST: (_has_file_list, "plausible C, header, or Make paths"),
    InputArtifactType.DEPENDENCY_FILE: (
        _has_dependency_rule,
        "a Make dependency rule with C/header paths",
    ),
    InputArtifactType.PREPROCESSED_SOURCE: (
        _has_preprocessed_c,
        "C syntax or preprocessor line markers",
    ),
    InputArtifactType.MACRO_LISTING: (_has_macros, "#define directives"),
}
