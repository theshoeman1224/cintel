from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from cintel.configuration.models import AppConfig
from cintel.domain.errors import ConfigurationError
from cintel.domain.models import (
    BuildConfiguration,
    BuildDiscoveryResult,
    CompilationUnit,
    FileKind,
)
from cintel.ports.services import BuildDiscoveryProvider
from cintel.ports.storage import AnalysisStorage
from cintel.application.scanning import RepositoryScanService
from cintel.utilities.hashing import stable_fingerprint, stable_id


class BuildDiscoveryService:
    def __init__(
        self,
        provider: BuildDiscoveryProvider,
        storage_factory: Callable[[Path], AnalysisStorage],
        repository_scanner: RepositoryScanService,
    ) -> None:
        self._provider = provider
        self._storage_factory = storage_factory
        self._repository_scanner = repository_scanner

    def create_configuration(
        self,
        app_config: AppConfig,
        *,
        makefile: Path | None,
        working_directory: Path | None,
        target: str | None,
        make_variables: tuple[tuple[str, str], ...],
        environment_overrides: tuple[tuple[str, str], ...],
        name: str,
        respect_make_timestamps: bool,
    ) -> BuildConfiguration:
        root = Path(app_config.repository_root).resolve()
        self._repository_scanner.scan(app_config)
        workdir = (
            _resolve_within_or_outside(working_directory, root)
            if working_directory
            else root
        )
        if not workdir.is_dir():
            raise ConfigurationError(
                f"Make working directory does not exist: {workdir}"
            )
        selected_makefile = _resolve_makefile(makefile, workdir)
        repository_id = stable_id("repository", str(root))

        storage = self._storage_factory(Path(app_config.database_path))
        try:
            storage.initialize()
            build_inputs = tuple(
                sorted(
                    (item.relative_path, item.content_sha256)
                    for item in storage.list_repository_files(repository_id)
                    if item.kind in {FileKind.MAKEFILE, FileKind.MAKE_FRAGMENT}
                )
            )
        finally:
            storage.close()

        identity = stable_fingerprint(
            {
                "repository": repository_id,
                "name": name,
                "makefile": str(selected_makefile) if selected_makefile else None,
                "working_directory": str(workdir),
                "target": target,
                "make_variables": make_variables,
                "environment_overrides": environment_overrides,
                "respect_make_timestamps": respect_make_timestamps,
            }
        )
        return BuildConfiguration(
            id=stable_id("build-configuration", identity),
            repository_id=repository_id,
            name=name,
            repository_root=str(root),
            makefile=str(selected_makefile) if selected_makefile else None,
            working_directory=str(workdir),
            target=target,
            make_variables=make_variables,
            environment_overrides=environment_overrides,
            build_input_hashes=build_inputs,
            respect_make_timestamps=respect_make_timestamps,
        )

    def preview(self, configuration: BuildConfiguration) -> tuple[str, ...]:
        return self._provider.command_request(configuration).arguments

    def discover(
        self, app_config: AppConfig, configuration: BuildConfiguration, force: bool = False
    ) -> BuildDiscoveryResult:
        input_fingerprint = self._provider.input_fingerprint(configuration)
        storage = self._storage_factory(Path(app_config.database_path))
        try:
            storage.initialize()
            if not force:
                cached = storage.get_cached_build_discovery(input_fingerprint)
                if cached is not None:
                    return replace(cached, from_cache=True)
            result = self._provider.discover(configuration)
            selected = {
                str(Path(path).resolve(strict=False))
                for path in result.selected_source_files
            }
            repository_sources = {
                str(Path(item.absolute_path).resolve(strict=False))
                for item in storage.list_repository_files(
                    configuration.repository_id
                )
                if item.kind is FileKind.C_SOURCE
            }
            result = replace(
                result,
                selected_source_files=tuple(sorted(selected)),
                excluded_source_files=tuple(sorted(repository_sources - selected)),
            )
            storage.save_build_discovery(result)
            storage.save_diagnostics(
                configuration.repository_id,
                result.diagnostics,
                context=f"build:{configuration.id}",
            )
            storage.save_capabilities(configuration.repository_id, result.capabilities)
            return result
        finally:
            storage.close()

    def list_units(
        self, app_config: AppConfig, build_configuration_name: str | None = None
    ) -> tuple[CompilationUnit, ...]:
        repository_id = stable_id(
            "repository", str(Path(app_config.repository_root).resolve())
        )
        storage = self._storage_factory(Path(app_config.database_path))
        try:
            storage.initialize()
            return storage.list_compilation_units(
                repository_id, build_configuration_name
            )
        finally:
            storage.close()

    def show_source(
        self,
        app_config: AppConfig,
        source_file: str,
        build_configuration_name: str | None = None,
    ) -> tuple[CompilationUnit, ...]:
        root = Path(app_config.repository_root).resolve()
        requested = Path(source_file)
        absolute = (
            requested.resolve(strict=False)
            if requested.is_absolute()
            else (root / requested).resolve(strict=False)
        )
        return tuple(
            unit
            for unit in self.list_units(app_config, build_configuration_name)
            if unit.compiler_invocation.source is not None
            and Path(unit.compiler_invocation.source.absolute).resolve(strict=False)
            == absolute
        )


def parse_assignments(values: list[str] | None, option_name: str) -> tuple[tuple[str, str], ...]:
    assignments: list[tuple[str, str]] = []
    for value in values or []:
        if "=" not in value:
            raise ConfigurationError(f"{option_name} requires NAME=value: {value}")
        name, item_value = value.split("=", 1)
        if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
            raise ConfigurationError(f"Invalid variable name for {option_name}: {name}")
        assignments.append((name, item_value))
    return tuple(assignments)


def _resolve_within_or_outside(path: Path, root: Path) -> Path:
    candidate = path.expanduser()
    return (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def _resolve_makefile(makefile: Path | None, working_directory: Path) -> Path | None:
    if makefile is not None:
        candidate = makefile.expanduser()
        if not candidate.is_absolute():
            candidate = working_directory / candidate
        candidate = candidate.resolve(strict=False)
        if not candidate.is_file():
            raise ConfigurationError(f"Makefile does not exist: {candidate}")
        return candidate
    for name in ("Makefile", "GNUmakefile", "makefile"):
        candidate = working_directory / name
        if candidate.is_file():
            return candidate.resolve()
    return None
