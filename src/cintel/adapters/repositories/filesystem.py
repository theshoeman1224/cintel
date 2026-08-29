from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    FileKind,
    Repository,
    RepositoryFile,
    RepositoryScan,
)
from cintel.utilities.hashing import sha256_file, stable_id
from cintel.utilities.paths import is_excluded


class FileSystemRepositoryDiscovery:
    """Conservative repository inventory using only local filesystem metadata."""

    def __init__(self, file_hasher: Callable[[Path], str] = sha256_file) -> None:
        self._file_hasher = file_hasher

    def discover(
        self,
        repository_root: str,
        repository_id: str,
        exclusions: tuple[str, ...],
        previous_files: tuple[RepositoryFile, ...] = (),
    ) -> RepositoryScan:
        root = Path(repository_root).expanduser().resolve()
        scanned_at = datetime.now(timezone.utc)
        repository = Repository(
            id=repository_id,
            root=str(root),
            name=root.name,
            created_at=scanned_at,
        )
        if not root.is_dir():
            return _unavailable_scan(repository, scanned_at, root)

        files, diagnostics, computed, reused = _scan_tree(
            root, repository_id, exclusions, previous_files, self._file_hasher
        )
        capabilities = _inventory_capabilities(files, diagnostics, computed, reused)
        return RepositoryScan(
            repository=repository,
            files=tuple(files),
            diagnostics=tuple(diagnostics),
            capabilities=capabilities,
            scanned_at=scanned_at,
            hashes_computed=computed,
            hashes_reused=reused,
        )


def _unavailable_scan(
    repository: Repository, scanned_at: datetime, root: Path
) -> RepositoryScan:
    diagnostic = Diagnostic(
        code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
        severity=DiagnosticSeverity.ERROR,
        message="The repository root does not exist or is not a directory.",
        technical_details=str(root),
        missing_capability="repository_inventory",
        recoverability=Recoverability.USER_ACTION,
        suggested_actions=("Provide an existing directory with --repository.",),
        related_paths=(str(root),),
    )
    return RepositoryScan(
        repository=repository,
        files=(),
        diagnostics=(diagnostic,),
        capabilities=(
            AnalysisCapability(
                name="repository_inventory",
                status=CapabilityStatus.UNAVAILABLE,
                reason="The repository root is unavailable.",
            ),
        ),
        scanned_at=scanned_at,
        hashes_computed=0,
        hashes_reused=0,
    )


def _record_walk_error(error: OSError, diagnostics: list[Diagnostic]) -> None:
    diagnostics.append(
        Diagnostic(
            code=DiagnosticCode.DIRECTORY_UNREADABLE,
            severity=DiagnosticSeverity.WARNING,
            message="A repository directory could not be read.",
            technical_details=str(error),
            missing_capability="complete_repository_inventory",
            recoverability=Recoverability.REDUCED_CAPABILITY,
            suggested_actions=("Check directory permissions and scan again.",),
            related_paths=(error.filename,) if error.filename else (),
        )
    )


def _scan_tree(
    root: Path,
    repository_id: str,
    exclusions: tuple[str, ...],
    previous_files: tuple[RepositoryFile, ...],
    file_hasher: Callable[[Path], str],
) -> tuple[list[RepositoryFile], list[Diagnostic], int, int]:
    previous = {item.relative_path: item for item in previous_files}
    files: list[RepositoryFile] = []
    diagnostics: list[Diagnostic] = []
    counters = _HashCounters()

    def record_walk_error(error: OSError) -> None:
        _record_walk_error(error, diagnostics)

    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False, onerror=record_walk_error
    ):
        relative_directory = Path(directory).relative_to(root)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not is_excluded(relative_directory / name, exclusions)
        )
        for name in sorted(file_names):
            scanned = _scan_file(
                name,
                relative_directory,
                root,
                exclusions,
                previous,
                repository_id,
                file_hasher,
                counters,
                diagnostics,
            )
            if scanned is not None:
                files.append(scanned)
    return files, diagnostics, counters.computed, counters.reused


class _HashCounters:
    __slots__ = ("computed", "reused")

    def __init__(self) -> None:
        self.computed = 0
        self.reused = 0


def _scan_file(
    name: str,
    relative_directory: Path,
    root: Path,
    exclusions: tuple[str, ...],
    previous: dict[str, RepositoryFile],
    repository_id: str,
    file_hasher: Callable[[Path], str],
    counters: _HashCounters,
    diagnostics: list[Diagnostic],
) -> RepositoryFile | None:
    relative_path = relative_directory / name
    if is_excluded(relative_path, exclusions):
        return None
    kind = _classify_file(name)
    if kind is None:
        return None
    absolute_path = root / relative_path
    relative_text = relative_path.as_posix()
    if absolute_path.is_symlink():
        diagnostics.append(_symlink_diagnostic(relative_text))
        return None
    try:
        stat = absolute_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        old = previous.get(relative_text)
        if (
            old is not None
            and old.size == stat.st_size
            and old.modified_at == modified_at
        ):
            content_hash = old.content_sha256
            counters.reused += 1
        else:
            content_hash = file_hasher(absolute_path)
            counters.computed += 1
    except OSError as error:
        diagnostics.append(_unreadable_file_diagnostic(relative_text, error))
        return None
    return RepositoryFile(
        id=stable_id("file", repository_id, relative_text),
        repository_id=repository_id,
        relative_path=relative_text,
        absolute_path=str(absolute_path),
        kind=kind,
        size=stat.st_size,
        modified_at=modified_at,
        content_sha256=content_hash,
    )


def _symlink_diagnostic(relative_text: str) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.SOURCE_SYMLINK_SKIPPED,
        severity=DiagnosticSeverity.WARNING,
        message="A symbolic-link source or build file was skipped.",
        technical_details="Scanning linked content could read outside the repository.",
        missing_capability="complete_repository_inventory",
        recoverability=Recoverability.REDUCED_CAPABILITY,
        suggested_actions=(
            "Replace the link with an in-repository file or inspect it manually.",
        ),
        related_paths=(relative_text,),
    )


def _unreadable_file_diagnostic(relative_text: str, error: OSError) -> Diagnostic:
    return Diagnostic(
        code=DiagnosticCode.FILE_UNREADABLE,
        severity=DiagnosticSeverity.WARNING,
        message="A repository file could not be read or hashed.",
        technical_details=str(error),
        missing_capability="complete_repository_inventory",
        recoverability=Recoverability.USER_ACTION,
        suggested_actions=("Check file permissions and scan again.",),
        related_paths=(relative_text,),
    )


def _inventory_capabilities(
    files: list[RepositoryFile],
    diagnostics: list[Diagnostic],
    computed: int,
    reused: int,
) -> tuple[AnalysisCapability, ...]:
    status = CapabilityStatus.DEGRADED if diagnostics else CapabilityStatus.AVAILABLE
    return (
        AnalysisCapability(
            name="repository_inventory",
            status=status,
            reason=(
                "Relevant repository files were inventoried."
                if not diagnostics
                else "The inventory completed with unreadable or skipped paths."
            ),
            evidence=(f"{len(files)} relevant files recorded",),
        ),
        AnalysisCapability(
            name="content_hashing",
            status=status,
            reason="SHA-256 hashes are stored for every recorded file.",
            evidence=(f"{computed} computed", f"{reused} reused"),
        ),
        AnalysisCapability(
            name="build_target_membership",
            status=CapabilityStatus.UNAVAILABLE,
            reason=(
                "Membership comes from Make build discovery runs; "
                "scanning records only build inputs."
            ),
        ),
    )


def _classify_file(name: str) -> FileKind | None:
    if name.endswith(".c"):
        return FileKind.C_SOURCE
    if name.endswith(".h"):
        return FileKind.C_HEADER
    if name in {"Makefile", "makefile", "GNUmakefile"}:
        return FileKind.MAKEFILE
    if name.endswith(".mk"):
        return FileKind.MAKE_FRAGMENT
    return None
