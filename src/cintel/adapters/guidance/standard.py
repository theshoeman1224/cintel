from __future__ import annotations

from pathlib import Path

from cintel.domain.diagnostics import Diagnostic, DiagnosticCode
from cintel.domain.models import BuildConfiguration, CommandInstruction, CommandRisk
from cintel.utilities.secrets import redact_value


class StandardInputGuidanceProvider:
    def instructions_for(
        self,
        repository_root: str,
        output_directory: str,
        diagnostics: tuple[Diagnostic, ...],
        build_configuration: BuildConfiguration | None = None,
    ) -> tuple[CommandInstruction, ...]:
        root = str(Path(repository_root).resolve())
        output = Path(output_directory).resolve() / "input"
        instructions: list[CommandInstruction] = []
        missing = {item.missing_capability for item in diagnostics}
        needs_make = not diagnostics or bool(
            missing
            & {
                "make_build_discovery",
                "complete_make_build_discovery",
                "compilation_units",
                "complete_command_discovery",
            }
        )
        if needs_make:
            arguments = ["make", "-n", "-B"]
            name = "default"
            if build_configuration is not None:
                name = build_configuration.name
                if build_configuration.makefile:
                    arguments.extend(("-f", build_configuration.makefile))
                if build_configuration.target:
                    arguments.append(build_configuration.target)
                arguments.extend(
                    f"{key}={_safe_value(key, value)}"
                    for key, value in build_configuration.make_variables
                )
            arguments.append("V=1")
            expected = output / f"{name}-make-dry-run.txt"
            instructions.append(
                CommandInstruction(
                    title="Capture verbose GNU Make dry-run output",
                    reason=(
                        "Build membership and exact per-file compiler arguments are unavailable."
                    ),
                    arguments=tuple(arguments),
                    working_directory=(
                        build_configuration.working_directory
                        if build_configuration and build_configuration.working_directory
                        else root
                    ),
                    expected_output_file=str(expected),
                    risk=CommandRisk.MAKEFILE_EVALUATION,
                    validation_steps=(
                        "Confirm the file is non-empty.",
                        "Confirm it contains compiler commands or a clear Make failure.",
                        "Review the file for secrets before sharing it.",
                    ),
                    resume_command=(
                        "cintel",
                        "--repository",
                        root,
                        "--input-file",
                        str(expected),
                        "--build-config",
                        name,
                        "resume",
                    ),
                    warnings=(
                        "make -n may still execute $(shell ...) expressions.",
                        "Do not run an unknown generation target automatically.",
                        "Environment values may contain secrets.",
                    ),
                )
            )
        related_paths = sorted(
            {
                path
                for diagnostic in diagnostics
                if diagnostic.code
                in {
                    DiagnosticCode.MISSING_SOURCE_FILE,
                    DiagnosticCode.MISSING_FORCED_INCLUDE,
                    DiagnosticCode.INPUT_ARTIFACT_STALE,
                }
                for path in diagnostic.related_paths
            }
        )
        for path in related_paths:
            instructions.append(
                CommandInstruction(
                    title=f"Locate missing build input {Path(path).name}",
                    reason="A compiler command references an input that is not currently present.",
                    arguments=("find", ".", "-name", Path(path).name, "-print"),
                    working_directory=root,
                    expected_output_file=None,
                    risk=CommandRisk.READ_ONLY,
                    validation_steps=(
                        "If found, confirm the file belongs to the selected configuration.",
                        "If generated, run only the documented project-specific generator.",
                    ),
                    resume_command=("cintel", "--repository", root, "resume"),
                    warnings=(
                        "Real builds and generation targets may modify repository files.",
                        "Do not run an unknown generation target automatically.",
                    ),
                )
            )
        if not instructions:
            instructions.append(
                CommandInstruction(
                    title="Capture a source-oriented repository file list",
                    reason="A portable inventory can support reduced-capability analysis.",
                    arguments=("find", ".", "-type", "f", "-print"),
                    working_directory=root,
                    expected_output_file=str(output / "repository-files.txt"),
                    risk=CommandRisk.READ_ONLY,
                    validation_steps=("Confirm paths belong to the selected repository.",),
                    resume_command=("cintel", "--repository", root, "resume"),
                )
            )
        return tuple(instructions)


def _safe_value(name: str, value: str) -> str:
    return redact_value(name, value, "<SET_LOCALLY>")
