"""Byte-for-byte golden tests for the Markdown report family renderers.

The complexity refactors must not change a single byte of rendered output.
Each case renders fixed synthetic report data through the public renderer
and compares the full document against a committed snapshot in
``tests/expected_reports``.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from cintel.adapters.reports import MarkdownReportRenderer
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
)
from cintel.domain.models import (
    AnalysisCapability,
    BuildConfiguration,
    CallGraphEdge,
    CallGraphReportData,
    CapabilityStatus,
    FileKind,
    IncludeIndexEntry,
    IncludeIndexReportData,
    Repository,
    RepositoryFile,
    RepositoryReportData,
    RepositoryScan,
    SymbolIndexEntry,
    SymbolIndexReportData,
)

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "expected_reports"
TIMESTAMP = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
REPOSITORY_ID = "repository-golden"


def render_report(report_name: str, data) -> str:
    """Render one report family through the public Markdown renderer."""
    return MarkdownReportRenderer().render(report_name, data)


def call_graph_empty() -> CallGraphReportData:
    return CallGraphReportData(edges=(), unresolved_count=0)


def call_graph_mixed() -> CallGraphReportData:
    return CallGraphReportData(
        edges=(
            CallGraphEdge(
                caller="main",
                caller_path="src/main.c",
                call_site_line=8,
                callee="helper",
                callee_path="src/util.c",
                callee_line=1,
                resolution="confirmed_direct",
            ),
            CallGraphEdge(
                caller="main",
                caller_path="src/main.c",
                call_site_line=9,
                callee="callback",
                callee_path=None,
                callee_line=None,
                resolution="unresolved",
            ),
            CallGraphEdge(
                caller="",
                caller_path="src/runner.c",
                call_site_line=2,
                callee="",
                callee_path=None,
                callee_line=None,
                resolution="unresolved",
            ),
            CallGraphEdge(
                caller="runner",
                caller_path="src/runner.c",
                call_site_line=3,
                callee="missing",
                callee_path=None,
                callee_line=None,
                resolution="unresolved",
            ),
        ),
        unresolved_count=3,
    )


def include_index_empty() -> IncludeIndexReportData:
    return IncludeIndexReportData(entries=(), unresolved_count=0)


def include_index_mixed() -> IncludeIndexReportData:
    return IncludeIndexReportData(
        entries=(
            IncludeIndexEntry(
                including_path="src/main.c",
                line=1,
                included_spelling='"project.h"',
                resolved_path="include/project.h",
            ),
            IncludeIndexEntry(
                including_path="src/main.c",
                line=2,
                included_spelling="<stdio.h>",
                resolved_path=None,
            ),
            IncludeIndexEntry(
                including_path="src/util.c",
                line=5,
                included_spelling="<missing.h>",
                resolved_path=None,
            ),
        ),
        unresolved_count=2,
    )


def symbol_index_empty() -> SymbolIndexReportData:
    return SymbolIndexReportData(entries=())


def symbol_index_states() -> SymbolIndexReportData:
    return SymbolIndexReportData(
        entries=(
            SymbolIndexEntry(
                name="zebra",
                kind="variable",
                relative_path="src/z.c",
                line=4,
                is_definition=None,
                linkage=None,
            ),
            SymbolIndexEntry(
                name="alpha",
                kind="function",
                relative_path="src/a.c",
                line=1,
                is_definition=True,
                linkage="external",
            ),
            SymbolIndexEntry(
                name="beta",
                kind="function",
                relative_path="src/b.c",
                line=2,
                is_definition=False,
                linkage="internal",
            ),
        )
    )


def _repository() -> Repository:
    return Repository(
        id=REPOSITORY_ID,
        root="/repo",
        name="repo",
        created_at=TIMESTAMP,
    )


def _file(
    file_id: str, relative_path: str, kind: FileKind, content_sha256: str
) -> RepositoryFile:
    return RepositoryFile(
        id=file_id,
        repository_id=REPOSITORY_ID,
        relative_path=relative_path,
        absolute_path=f"/repo/{relative_path}",
        kind=kind,
        size=10,
        modified_at=TIMESTAMP,
        content_sha256=content_sha256,
    )


def repository_inventory_minimal() -> RepositoryReportData:
    scan = RepositoryScan(
        repository=_repository(),
        files=(),
        diagnostics=(
            Diagnostic(
                code=DiagnosticCode.REPOSITORY_ROOT_UNAVAILABLE,
                severity=DiagnosticSeverity.WARNING,
                message="repository root is not readable",
                technical_details="Permission denied.",
                suggested_actions=(
                    "Run `cintel doctor`.",
                    "Check the mount.",
                ),
            ),
            Diagnostic(
                code=DiagnosticCode.MAKE_NOT_EXECUTABLE,
                severity=DiagnosticSeverity.INFO,
                message="make was not found",
            ),
        ),
        capabilities=(
            AnalysisCapability(
                name="make",
                status=CapabilityStatus.AVAILABLE,
                reason="GNU Make found",
                evidence=("/usr/bin/make",),
            ),
            AnalysisCapability(
                name="gcc",
                status=CapabilityStatus.UNAVAILABLE,
                reason="no C compiler on PATH",
            ),
        ),
        scanned_at=TIMESTAMP,
        hashes_computed=0,
        hashes_reused=0,
    )
    return RepositoryReportData(
        scan=scan,
        build_configurations=(),
        compilation_unit_count=0,
        analyzed_file_count=0,
    )


def repository_inventory_populated() -> RepositoryReportData:
    scan = RepositoryScan(
        repository=_repository(),
        files=(
            _file("file-a", "main.c", FileKind.C_SOURCE, "a" * 64),
            _file("file-b", "src/app.c", FileKind.C_SOURCE, "b" * 64),
            _file("file-c", "include/app.h", FileKind.C_HEADER, "c" * 64),
            _file("file-d", "Makefile", FileKind.MAKEFILE, "d" * 64),
        ),
        diagnostics=(),
        capabilities=(
            AnalysisCapability(
                name="make",
                status=CapabilityStatus.AVAILABLE,
                reason="GNU Make found",
                evidence=("/usr/bin/make",),
            ),
        ),
        scanned_at=TIMESTAMP,
        hashes_computed=2,
        hashes_reused=2,
    )
    return RepositoryReportData(
        scan=scan,
        build_configurations=(
            BuildConfiguration(
                id="build-1",
                repository_id=REPOSITORY_ID,
                name="debug",
                repository_root="/repo",
                target="debug",
            ),
        ),
        compilation_unit_count=2,
        analyzed_file_count=3,
    )


GOLDEN_CASES = (
    ("call_graph_empty", "call_graph", call_graph_empty, "call_graph_empty.md"),
    ("call_graph_mixed", "call_graph", call_graph_mixed, "call_graph_mixed.md"),
    (
        "include_index_empty",
        "include_index",
        include_index_empty,
        "include_index_empty.md",
    ),
    (
        "include_index_mixed",
        "include_index",
        include_index_mixed,
        "include_index_mixed.md",
    ),
    (
        "symbol_index_empty",
        "symbol_index",
        symbol_index_empty,
        "symbol_index_empty.md",
    ),
    (
        "symbol_index_states",
        "symbol_index",
        symbol_index_states,
        "symbol_index_states.md",
    ),
    (
        "repository_inventory_minimal",
        "repository_inventory",
        repository_inventory_minimal,
        "repository_inventory_minimal.md",
    ),
    (
        "repository_inventory_populated",
        "repository_inventory",
        repository_inventory_populated,
        "repository_inventory_populated.md",
    ),
)


class MarkdownRendererGoldenTests(unittest.TestCase):
    def test_rendered_documents_match_golden_snapshots(self) -> None:
        for case, report_name, builder, filename in GOLDEN_CASES:
            with self.subTest(case=case):
                expected = (GOLDEN_ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual(expected, render_report(report_name, builder()))


if __name__ == "__main__":
    unittest.main()
