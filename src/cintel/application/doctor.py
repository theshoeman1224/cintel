from __future__ import annotations

import fnmatch
import os
import shutil
import sys
from pathlib import Path

from cintel.configuration.models import AppConfig
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    CommandRequest,
    CommandRisk,
    DoctorReport,
    ToolStatus,
)
from cintel.ports.commands import CommandRunner


class DoctorService:
    def __init__(self, command_runner: CommandRunner) -> None:
        self._runner = command_runner

    def inspect(self, config: AppConfig) -> DoctorReport:
        root = Path(config.repository_root)
        command_working_directory = root if root.is_dir() else Path.cwd()
        tools = self._inspect_tools(command_working_directory)
        detected = self._detect_inputs(root, config.exclusion_patterns)
        writable = _directory_can_be_written(Path(config.output_directory))
        diagnostics: list[Diagnostic] = []
        actions: list[str] = []

        if not root.is_dir():
            diagnostics.append(
                Diagnostic(
                    code="CI-REPO-001",
                    severity=DiagnosticSeverity.ERROR,
                    message="The repository root does not exist or is not a directory.",
                    technical_details=str(root),
                    missing_capability="repository_access",
                    recoverability=Recoverability.USER_ACTION,
                    suggested_actions=("Provide an existing directory with --repository.",),
                    related_paths=(str(root),),
                )
            )
            actions.append("Select an existing repository directory.")

        tool_by_name = {tool.name: tool for tool in tools}
        make_available = tool_by_name["make"].available
        gcc_available = any(
            tool.available for tool in tools if tool.name == "gcc" or tool.name.endswith("-gcc")
        )

        if not make_available:
            diagnostics.append(
                Diagnostic(
                    code="CI-BUILD-001",
                    severity=DiagnosticSeverity.WARNING,
                    message="GNU Make was not found.",
                    technical_details="Build discovery cannot run Make dry-run evaluation.",
                    missing_capability="make_build_discovery",
                    recoverability=Recoverability.REDUCED_CAPABILITY,
                    suggested_actions=(
                        "Install GNU Make without requiring cintel to run as root, "
                        "or later import saved dry-run output.",
                    ),
                )
            )
            actions.append("Continue with repository-only analysis when Phase 2 is available.")

        if not gcc_available:
            diagnostics.append(
                Diagnostic(
                    code="CI-COMP-001",
                    severity=DiagnosticSeverity.WARNING,
                    message="GCC or a cross-GCC executable was not found.",
                    technical_details="Compiler enrichment will be unavailable.",
                    missing_capability="gcc_enrichment",
                    recoverability=Recoverability.REDUCED_CAPABILITY,
                    suggested_actions=(
                        "Make discovery and conservative source parsing can still be used.",
                    ),
                )
            )
            actions.append("Use deterministic reduced-capability analysis without GCC.")

        if not writable:
            diagnostics.append(
                Diagnostic(
                    code="CI-REPO-001",
                    severity=DiagnosticSeverity.ERROR,
                    message="The output directory cannot be created or written.",
                    technical_details=config.output_directory,
                    missing_capability="persistent_analysis",
                    recoverability=Recoverability.USER_ACTION,
                    suggested_actions=("Choose a writable --output-directory.",),
                    related_paths=(config.output_directory,),
                )
            )
            actions.append("Select a writable output directory before running cintel init.")

        if not detected["makefiles"]:
            diagnostics.append(
                Diagnostic(
                    code="CI-BUILD-002",
                    severity=DiagnosticSeverity.INFO,
                    message="No Makefile or .mk file was detected.",
                    missing_capability="make_build_discovery",
                    recoverability=Recoverability.REDUCED_CAPABILITY,
                    suggested_actions=(
                        "Specify a Makefile later or continue with repository scanning.",
                    ),
                )
            )

        capabilities = (
            AnalysisCapability(
                name="repository_initialization",
                status=CapabilityStatus.AVAILABLE if writable else CapabilityStatus.UNAVAILABLE,
                reason="Output location is writable." if writable else "Output location is not writable.",
            ),
            AnalysisCapability(
                name="make_build_discovery",
                status=CapabilityStatus.AVAILABLE if make_available else CapabilityStatus.UNAVAILABLE,
                reason="GNU Make is available." if make_available else "GNU Make is unavailable.",
            ),
            AnalysisCapability(
                name="gcc_enrichment",
                status=CapabilityStatus.AVAILABLE if gcc_available else CapabilityStatus.UNAVAILABLE,
                reason="A GCC executable is available." if gcc_available else "No GCC executable was found.",
            ),
            AnalysisCapability(
                name="offline_deterministic_analysis",
                status=CapabilityStatus.AVAILABLE,
                reason="The core uses local files and standard-library adapters only.",
            ),
            AnalysisCapability(
                name="ai_generation",
                status=CapabilityStatus.UNAVAILABLE,
                reason="AI is disabled by default and not implemented in the MVP foundation.",
            ),
        )

        if not actions:
            actions.append("Run `cintel init <repository>` to create the local workspace.")

        return DoctorReport(
            repository_root=str(root),
            python_version=sys.version.split()[0],
            tools=tools,
            output_directory_writable=writable,
            detected_inputs=detected,
            capabilities=capabilities,
            diagnostics=tuple(diagnostics),
            recommended_actions=tuple(actions),
        )

    def _inspect_tools(self, working_directory: Path) -> tuple[ToolStatus, ...]:
        specs = (
            ("make", ("--version",)),
            ("gcc", ("--version",)),
            ("cc", ("--version",)),
            ("nm", ("--version",)),
            ("objdump", ("--version",)),
            ("readelf", ("--version",)),
            ("find", ("--version",)),
            ("grep", ("--version",)),
            ("dot", ("-V",)),
        )
        statuses = [self._tool_status(name, args, working_directory) for name, args in specs]
        known_paths = {status.path for status in statuses}
        for name, path in _cross_gcc_candidates():
            if path not in known_paths:
                statuses.append(self._tool_status(name, ("--version",), working_directory, path))
        return tuple(statuses)

    def _tool_status(
        self,
        name: str,
        version_arguments: tuple[str, ...],
        working_directory: Path,
        known_path: str | None = None,
    ) -> ToolStatus:
        path = known_path or shutil.which(name)
        if path is None:
            return ToolStatus(name=name, path=None, version=None, available=False)
        result = self._runner.run(
            CommandRequest(
                arguments=(path, *version_arguments),
                working_directory=str(working_directory),
                timeout_seconds=5,
                risk=CommandRisk.READ_ONLY,
            )
        )
        combined = result.standard_output.strip() or result.standard_error.strip()
        first_line = combined.splitlines()[0] if combined else None
        return ToolStatus(
            name=name,
            path=path,
            version=first_line,
            available=result.exit_code == 0,
            details="" if result.exit_code == 0 else f"Version command exited {result.exit_code}",
        )

    @staticmethod
    def _detect_inputs(
        root: Path, exclusions: tuple[str, ...]
    ) -> dict[str, tuple[str, ...]]:
        categories: dict[str, list[str]] = {
            "makefiles": [],
            "build_logs": [],
            "dependency_files": [],
            "object_files": [],
            "compile_databases": [],
        }
        if not root.is_dir():
            return {name: () for name in categories}

        for directory, names, files in os.walk(root):
            relative_dir = Path(directory).relative_to(root)
            names[:] = [
                name
                for name in names
                if not _excluded(relative_dir / name, exclusions)
            ]
            for filename in files:
                relative = (relative_dir / filename).as_posix()
                lower = filename.lower()
                if filename in {"Makefile", "makefile", "GNUmakefile"} or filename.endswith(".mk"):
                    categories["makefiles"].append(relative)
                if lower.endswith((".log", ".buildlog")):
                    categories["build_logs"].append(relative)
                if filename.endswith(".d"):
                    categories["dependency_files"].append(relative)
                if filename.endswith(".o"):
                    categories["object_files"].append(relative)
                if filename == "compile_commands.json":
                    categories["compile_databases"].append(relative)
        return {name: tuple(sorted(values)) for name, values in categories.items()}


def _directory_can_be_written(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _excluded(relative: Path, patterns: tuple[str, ...]) -> bool:
    value = relative.as_posix()
    return any(
        fnmatch.fnmatch(relative.name, pattern) or fnmatch.fnmatch(value, pattern)
        for pattern in patterns
    )


def _cross_gcc_candidates() -> tuple[tuple[str, str], ...]:
    results: dict[str, str] = {}
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        path = Path(directory)
        if not path.is_dir():
            continue
        try:
            entries = path.iterdir()
            for candidate in entries:
                if candidate.name.endswith("-gcc") and os.access(candidate, os.X_OK):
                    results.setdefault(candidate.name, str(candidate))
        except OSError:
            continue
    return tuple(sorted(results.items()))
