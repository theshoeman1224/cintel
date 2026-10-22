"""The analysis scope that queries and reports read.

Storage keeps every analysis result ever produced: file-scoped results from
plain ``analyze`` runs and per-unit results for each build configuration.
Reading all of them at once mixes scopes and yields contradictory answers,
such as one call site that is both resolved and unresolved. The scope is the
set of results the latest ``analyze`` run used, reconstructed from the build
configuration name that run recorded in its workflow state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from cintel.domain.models import SourceAnalysisResult, WorkflowStage
from cintel.ports.storage import AnalysisStorage

BUILD_CONFIGURATION_DETAIL = "build_configuration"


class _FromAnalysis(Protocol):
    @property
    def analysis_id(self) -> str: ...


_Item = TypeVar("_Item", bound=_FromAnalysis)


@dataclass(frozen=True, slots=True)
class AnalysisScope:
    """Analysis result ids visible to readers; ``None`` means unrestricted."""

    analysis_ids: frozenset[str] | None

    def keep(self, items: Iterable[_Item]) -> tuple[_Item, ...]:
        """Drop items produced by analyses outside the scope."""
        if self.analysis_ids is None:
            return tuple(items)
        return tuple(item for item in items if item.analysis_id in self.analysis_ids)

    def keep_results(
        self, results: Iterable[SourceAnalysisResult]
    ) -> tuple[SourceAnalysisResult, ...]:
        """Drop analysis results outside the scope."""
        if self.analysis_ids is None:
            return tuple(results)
        return tuple(item for item in results if item.id in self.analysis_ids)


def scoped_results(
    results: Iterable[SourceAnalysisResult], unit_ids: frozenset[str]
) -> tuple[SourceAnalysisResult, ...]:
    """Per-unit results for ``unit_ids`` plus file-scoped results elsewhere.

    This mirrors how ``analyze`` selects targets: a file compiled by the
    configuration is analyzed per unit, every other C file file-scoped.
    """
    stored = tuple(results)
    unit_results = [item for item in stored if item.compilation_unit_id in unit_ids]
    covered = {item.repository_file_id for item in unit_results}
    file_scoped = [
        item
        for item in stored
        if item.compilation_unit_id is None
        and item.repository_file_id not in covered
    ]
    return tuple(unit_results + file_scoped)


def active_scope(storage: AnalysisStorage, repository_id: str) -> AnalysisScope:
    """The scope of the latest ``analyze`` run, or unrestricted if unknown."""
    state = next(
        (
            item
            for item in storage.list_workflow_states(repository_id)
            if item.stage == WorkflowStage.SOURCE_ANALYSIS
        ),
        None,
    )
    details = dict(state.details) if state is not None else {}
    if BUILD_CONFIGURATION_DETAIL not in details:
        # Databases analyzed before the scope was recorded stay readable.
        return AnalysisScope(analysis_ids=None)
    name = details[BUILD_CONFIGURATION_DETAIL] or None
    unit_ids = (
        frozenset(
            unit.id for unit in storage.list_compilation_units(repository_id, name)
        )
        if name is not None
        else frozenset()
    )
    results = scoped_results(storage.list_source_analyses(repository_id), unit_ids)
    return AnalysisScope(analysis_ids=frozenset(item.id for item in results))
