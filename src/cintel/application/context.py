"""Deterministic, budgeted context packages for a single function.

The service assembles a :class:`ContextPackage` from stored analysis state
and the defining source file. Section content is deterministic: the same
stored state and budget always produce the same package, section order, and
output file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cintel.application.queries import (
    FunctionCandidates,
    FunctionDetail,
    SymbolEntry,
    SymbolQueryService,
)
from cintel.application.storage_session import storage_session
from cintel.domain.models import (
    AnalysisCapability,
    CapabilityStatus,
    CompilationUnit,
    ContextPackage,
    FunctionSymbol,
    GeneratedReportMetadata,
    GlobalUsageRelationship,
    IncludeRelationship,
    MacroSymbol,
    SourceAnalysisResult,
    TypeSymbol,
    VariableSymbol,
)
from cintel.configuration.models import AppConfig
from cintel.ports.artifacts import ArtifactWriter
from cintel.ports.storage import AnalysisStorage
from cintel.utilities.hashing import sha256_text, stable_id
from cintel.utilities.paths import stable_repository_id

DEFAULT_CONTEXT_BUDGET = 8000

_EXCERPT_FALLBACK_LINES = 15

_CODE_SECTIONS = frozenset({"Definition", "Preceding comment"})


@dataclass(frozen=True, slots=True)
class ContextResult:
    package: ContextPackage
    output_path: str


class ContextService:
    def __init__(
        self,
        queries: SymbolQueryService,
        artifact_writer: ArtifactWriter,
        storage_factory: Callable[[Path], AnalysisStorage],
    ) -> None:
        self._queries = queries
        self._artifact_writer = artifact_writer
        self._storage_factory = storage_factory

    def context_function(
        self,
        app_config: AppConfig,
        name: str,
        *,
        file: str | None = None,
        budget: int = DEFAULT_CONTEXT_BUDGET,
    ) -> ContextResult | FunctionCandidates:
        if budget <= 0:
            raise ValueError("Context budget must be positive")
        detail = self._queries.function(app_config, name, file=file)
        if isinstance(detail, FunctionCandidates):
            return detail
        with storage_session(
            self._storage_factory, app_config.database_path
        ) as storage:
            repository_id = stable_repository_id(app_config.repository_root)
            files = {
                item.id: item
                for item in storage.list_repository_files(repository_id)
            }
            file_id = _file_id_for(files, detail.definition.relative_path)
            analysis = self._analysis_for(storage, file_id, detail.definition)
            unit = self._unit_for(storage, repository_id, detail.definition)
            sections = _build_sections(detail, analysis, unit, files)
            package = _apply_budget(sections, budget, detail)
            output_path = self._write_package(
                app_config, repository_id, package, detail.definition
            )
            return ContextResult(package=package, output_path=str(output_path))

    def _analysis_for(
        self,
        storage: AnalysisStorage,
        file_id: str | None,
        definition: SymbolEntry,
    ) -> SourceAnalysisResult | None:
        if file_id is None:
            return None
        for result in storage.list_source_analyses_for_file(file_id):
            if result.id == definition.analysis_id:
                return result
        return None

    def _unit_for(
        self,
        storage: AnalysisStorage,
        repository_id: str,
        definition: SymbolEntry,
    ) -> CompilationUnit | None:
        if definition.compilation_unit_id is None:
            return None
        for unit in storage.list_compilation_units(repository_id):
            if unit.id == definition.compilation_unit_id:
                return unit
        return None

    def _write_package(
        self,
        app_config: AppConfig,
        repository_id: str,
        package: ContextPackage,
        definition: SymbolEntry,
    ) -> Path:
        directory = Path(app_config.output_directory) / "context"
        if definition.relative_path:
            slug = definition.relative_path.replace("/", "_").replace(".", "_")
            filename = f"{definition.name}__{slug}.md"
        else:
            filename = f"{definition.name}.md"
        output_path = directory / filename
        content = render_context_markdown(package)
        self._artifact_writer.write_text(output_path, content)
        with storage_session(
            self._storage_factory, app_config.database_path
        ) as storage:
            storage.save_report_metadata(
                GeneratedReportMetadata(
                    id=stable_id(
                        "report",
                        repository_id,
                        f"function_context:{filename}",
                        "markdown",
                    ),
                    repository_id=repository_id,
                    report_name=f"function_context:{filename}",
                    format="markdown",
                    file_path=str(output_path.resolve()),
                    content_sha256=sha256_text(content),
                    generated_at=datetime.now(timezone.utc),
                )
            )
        return output_path


def _build_sections(
    detail: FunctionDetail,
    analysis: SourceAnalysisResult | None,
    unit: CompilationUnit | None,
    files: dict,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    definition = detail.definition
    sections.append(("Definition", _definition_body(definition, files)))
    if detail.declarations:
        sections.append(
            (
                "Declarations",
                "\n".join(
                    f"{entry.relative_path}:{entry.line}  {entry.detail}"
                    for entry in detail.declarations
                ),
            )
        )
    comment = _preceding_comment(definition, files)
    if comment:
        sections.append(("Preceding comment", comment))
    sections.append(("Callers", _sites_body(detail.callers)))
    sections.append(("Callees", _sites_body(detail.callees)))
    if analysis is not None:
        globals_body = _globals_body(analysis, definition.symbol_id)
        if globals_body:
            sections.append(("Globals used", globals_body))
        types_body = _types_body(analysis)
        if types_body:
            sections.append(("Local types", types_body))
        macros_body = _macros_body(analysis)
        if macros_body:
            sections.append(("Macros in file", macros_body))
        headers_body = _headers_body(analysis, files, detail.declarations)
        if headers_body:
            sections.append(("Relevant headers", headers_body))
    sections.append(("Compiler context", _compiler_context(unit)))
    sections.append(("Notes", _notes(detail, analysis)))
    return sections


def _file_id_for(files: dict, relative_path: str) -> str | None:
    for file_id, item in files.items():
        if item.relative_path == relative_path:
            return file_id
    return None


def _definition_body(definition: SymbolEntry, files: dict) -> str:
    file_id = _file_id_for(files, definition.relative_path)
    if file_id is None:
        return f"{definition.detail}  [{definition.relative_path}:{definition.line}]"
    lines = Path(files[file_id].absolute_path).read_text(encoding="utf-8").splitlines()
    start = max(definition.line - 1, 0)
    if definition.end_line is not None:
        end = definition.end_line
    else:
        end = min(definition.line - 1 + _EXCERPT_FALLBACK_LINES, len(lines) - 1)
    return "\n".join(lines[start : end + 1])


def _preceding_comment(definition: SymbolEntry, files: dict) -> str:
    file_id = _file_id_for(files, definition.relative_path)
    if file_id is None:
        return ""
    lines = Path(files[file_id].absolute_path).read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    index = definition.line - 2
    while index >= 0:
        stripped = lines[index].strip()
        if stripped.startswith(("//", "/*", "*")) or stripped == "*/":
            collected.append(lines[index])
            index -= 1
            continue
        break
    return "\n".join(reversed(collected))


def _sites_body(sites) -> str:
    if not sites:
        return "none"
    return "\n".join(
        f"{site.function_name} ({site.resolution}) {site.relative_path}:{site.line}"
        for site in sites
    )


def _globals_body(analysis: SourceAnalysisResult, function_id: str) -> str:
    symbols_by_id = {symbol.id: symbol for symbol in analysis.symbols}
    lines: list[str] = []
    seen: set[tuple[str, int]] = set()
    for relationship in analysis.relationships:
        if not isinstance(relationship, GlobalUsageRelationship):
            continue
        if relationship.function_id != function_id:
            continue
        variable = symbols_by_id.get(relationship.variable_id or "")
        location = (
            variable.location if isinstance(variable, VariableSymbol) else None
        )
        key = (relationship.variable_spelling, location.line if location else 0)
        if key in seen:
            continue
        seen.add(key)
        spelling = (
            variable.type_spelling or "unknown type"
            if isinstance(variable, VariableSymbol)
            else "unknown type"
        )
        where = (
            f"{location.path}:{location.line}" if location else "location unknown"
        )
        lines.append(f"{relationship.variable_spelling}: {spelling} ({where})")
    return "\n".join(lines)


def _types_body(analysis: SourceAnalysisResult) -> str:
    lines: list[str] = []
    for symbol in analysis.symbols:
        if not isinstance(symbol, TypeSymbol):
            continue
        spelling = (
            f"{symbol.type_kind}: {symbol.underlying_type}"
            if symbol.underlying_type
            else symbol.type_kind
        )
        state = "definition" if symbol.is_definition else "declaration"
        lines.append(
            f"{symbol.name} [{state}] {spelling} "
            f"{symbol.location.path}:{symbol.location.line}"
        )
    return "\n".join(lines)


def _macros_body(analysis: SourceAnalysisResult) -> str:
    lines: list[str] = []
    for symbol in analysis.symbols:
        if not isinstance(symbol, MacroSymbol):
            continue
        lines.append(f"{symbol.name} = {symbol.replacement or ''}".rstrip())
    return "\n".join(lines)


def _headers_body(analysis: SourceAnalysisResult, files: dict, declarations) -> str:
    lines: list[str] = []
    for relationship in analysis.relationships:
        if not isinstance(relationship, IncludeRelationship):
            continue
        if relationship.resolved_file_id is not None:
            origin = files.get(relationship.resolved_file_id)
            target = (
                origin.relative_path
                if origin is not None
                else relationship.resolved_file_id
            )
            lines.append(f"{relationship.included_spelling} -> {target}")
        else:
            lines.append(f"{relationship.included_spelling} -> unresolved")
    for entry in declarations:
        lines.append(f"{entry.relative_path} -> declaration of {entry.name}")
    return "\n".join(lines)


def _compiler_context(unit: CompilationUnit | None) -> str:
    if unit is None:
        return (
            "unconfigured: file-scoped analysis without compiler defines or "
            "include paths"
        )
    arguments = unit.compiler_invocation.arguments
    lines = [f"compiler: {unit.compiler_invocation.compiler_executable}"]
    if arguments.language_standard:
        lines.append(f"standard: {arguments.language_standard}")
    for definition in arguments.defines:
        value = f"={definition.value}" if definition.value is not None else ""
        lines.append(f"-D{definition.name}{value}")
    for include in arguments.include_paths:
        marker = "-isystem" if include.is_system else "-I"
        lines.append(f"{marker} {include.path.original}")
    for forced in arguments.forced_includes:
        lines.append(f"-include {forced.original}")
    return "\n".join(lines)


def _notes(detail: FunctionDetail, analysis: SourceAnalysisResult | None) -> str:
    lines = [
        "provenance: "
        + (
            f"parser {analysis.parser_name} {analysis.parser_version}, "
            f"analysis status {analysis.status.value}"
            if analysis is not None
            else "stored analysis not found"
        ),
        "conservative analysis: function-pointer dispatch, macro-generated "
        "code, and conditional compilation are not fully resolved",
        "call resolution: same-file static definitions first, then a single "
        "repository-wide definition; ambiguous targets stay unresolved",
    ]
    if analysis is not None:
        for symbol in analysis.symbols:
            if (
                isinstance(symbol, FunctionSymbol)
                and symbol.id == detail.definition.symbol_id
            ):
                lines.append(
                    f"definition confidence: {symbol.confidence:.2f} "
                    f"({symbol.linkage.value} linkage)"
                )
                for evidence in symbol.evidence:
                    lines.append(f"evidence: {evidence.description}")
    resolved = sum(
        1 for site in detail.callers if site.resolution == "confirmed_direct"
    )
    lines.append(
        f"callers resolved: {resolved} of {len(detail.callers)} recorded call sites"
    )
    return "\n".join(lines)


def _apply_budget(
    sections: list[tuple[str, str]],
    budget: int,
    detail: FunctionDetail,
) -> ContextPackage:
    selected: list[tuple[str, str]] = []
    used = 0
    omitted: list[str] = []
    exhausted = False
    for index, (title, body) in enumerate(sections):
        cost = len(title) + len(body)
        if exhausted:
            omitted.append(title)
            continue
        if used + cost <= budget:
            selected.append((title, body))
            used += cost
            continue
        # Sections are taken strictly in priority order: the first section
        # that does not fit ends inclusion. The definition excerpt (index 0)
        # is the exception — it is truncated to the remaining budget.
        exhausted = True
        omitted.append(title)
        if index == 0:
            marker = "… [truncated]"
            remaining = budget - used - len(title) - len(marker)
            if remaining > 0:
                selected.append((title, body[:remaining] + marker))
                used = budget
    if omitted:
        title = "Omitted sections"
        body = ", ".join(omitted)
        marker = "… [truncated]"
        cost = len(title) + len(body)
        if used + cost <= budget:
            selected.append((title, body))
            used += cost
        else:
            remaining = budget - used - len(title) - len(marker)
            if remaining > 0:
                selected.append((title, body[:remaining] + marker))
                used = budget
    capabilities = (
        AnalysisCapability(
            name="deterministic_context",
            status=CapabilityStatus.AVAILABLE if not omitted else CapabilityStatus.DEGRADED,
            reason=(
                "all sections fit the budget"
                if not omitted
                else f"sections exceeded the {budget} character budget"
            ),
            evidence=(f"budget={budget}", f"used={used}"),
        ),
    )
    return ContextPackage(
        function_id=detail.definition.symbol_id,
        title=(
            f"Context for {detail.definition.name} "
            f"({detail.definition.relative_path}:{detail.definition.line})"
        ),
        sections=tuple(selected),
        character_budget=budget,
        used_characters=used,
        capabilities=capabilities,
        evidence=(),
    )


def render_context_markdown(package: ContextPackage) -> str:
    lines = [f"# {package.title}", ""]
    for title, body in package.sections:
        lines.append(f"## {title}")
        lines.append("")
        if title in _CODE_SECTIONS:
            lines.append("```c")
            lines.append(body)
            lines.append("```")
        else:
            lines.append(body)
        lines.append("")
    lines.append("---")
    lines.append(
        f"Budget: {package.used_characters} of {package.character_budget} "
        "characters used."
    )
    return "\n".join(lines) + "\n"
