"""Conservative, replaceable C source parser for the Phase 5A foundation."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cintel.adapters.parsing.lexical import MaskIssue, mask_c_non_code
from cintel.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    Recoverability,
)
from cintel.domain.models import (
    CompilationUnit,
    EvidenceKind,
    FileKind,
    FunctionSymbol,
    IncludeRelationship,
    Linkage,
    MacroSymbol,
    RelationshipEvidence,
    RepositoryFile,
    SourceAnalysisResult,
    SourceAnalysisStatus,
    SourceLocation,
    SourceRelationship,
    SourceSymbol,
    TypeSymbol,
    VariableSymbol,
)
from cintel.utilities.hashing import stable_fingerprint, stable_id

PARSER_NAME = "conservative-c"
PARSER_VERSION = "1"

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_CONTROL_NAMES = {"if", "for", "while", "switch", "return", "sizeof", "_Alignof"}
_STORAGE_WORDS = {"extern", "static", "inline", "_Noreturn", "register", "auto"}

_EXACT_CONFIDENCE = 1.0
_MACRO_HEURISTIC_CONFIDENCE = 0.8
_FUNCTION_DEFINITION_CONFIDENCE = 0.9
_FUNCTION_DECLARATION_CONFIDENCE = 0.85
_TAGGED_TYPE_CONFIDENCE = 0.9
_TYPEDEF_CONFIDENCE = 0.85
_VARIABLE_CONFIDENCE = 0.8


@dataclass(frozen=True, slots=True)
class _Directive:
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Construct:
    kind: str
    start: int
    end: int
    header_end: int | None = None


@dataclass(frozen=True, slots=True)
class _ConstructIssue:
    message: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _FunctionHeader:
    name: str
    name_offset: int
    return_type: str
    parameters: tuple[str, ...]
    linkage: Linkage


@dataclass(frozen=True, slots=True)
class _AnalysisScope:
    """Values shared by every result produced for one parse invocation."""

    repository_file: RepositoryFile
    compilation_unit_id: str | None
    scope_id: str
    fingerprint: str
    analyzed_at: datetime

    @classmethod
    def build(
        cls,
        repository_file: RepositoryFile,
        compilation_unit: CompilationUnit | None,
    ) -> _AnalysisScope:
        return cls(
            repository_file=repository_file,
            compilation_unit_id=(
                compilation_unit.id if compilation_unit else None
            ),
            scope_id=stable_id(
                "source-analysis",
                repository_file.id,
                compilation_unit.id if compilation_unit else "unconfigured",
            ),
            fingerprint=stable_fingerprint(
                {
                    "source_hash": repository_file.content_sha256,
                    "compilation_unit": (
                        compilation_unit.fingerprint if compilation_unit else None
                    ),
                    "parser": PARSER_NAME,
                    "parser_version": PARSER_VERSION,
                }
            ),
            analyzed_at=datetime.now(timezone.utc),
        )

    def result(
        self,
        status: SourceAnalysisStatus,
        symbols: tuple[SourceSymbol, ...] = (),
        relationships: tuple[SourceRelationship, ...] = (),
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> SourceAnalysisResult:
        return SourceAnalysisResult(
            id=self.scope_id,
            repository_id=self.repository_file.repository_id,
            repository_file_id=self.repository_file.id,
            compilation_unit_id=self.compilation_unit_id,
            source_hash=self.repository_file.content_sha256,
            analysis_fingerprint=self.fingerprint,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            status=status,
            symbols=tuple(_deduplicate_symbols(list(symbols))),
            relationships=tuple(_deduplicate_relationships(list(relationships))),
            diagnostics=tuple(_deduplicate_diagnostics(list(diagnostics))),
            analyzed_at=self.analyzed_at,
        )


class _Locations:
    def __init__(self, source: str, path: str) -> None:
        self._source = source
        self._path = path
        self._line_starts = [0]
        self._line_starts.extend(
            index + 1 for index, character in enumerate(source) if character == "\n"
        )

    def location(self, start: int, end: int | None = None) -> SourceLocation:
        bounded_start = max(0, min(start, len(self._source)))
        bounded_end = max(bounded_start, min(end or bounded_start + 1, len(self._source)))
        line_index = bisect.bisect_right(self._line_starts, bounded_start) - 1
        end_index = bisect.bisect_right(
            self._line_starts, max(bounded_start, bounded_end - 1)
        ) - 1
        return SourceLocation(
            path=self._path,
            line=line_index + 1,
            column=bounded_start - self._line_starts[line_index] + 1,
            end_line=end_index + 1,
            end_column=bounded_end - self._line_starts[end_index] + 1,
        )


class ConservativeCSourceParser:
    """Extracts high-confidence surface syntax without claiming C semantics."""

    def parse(
        self, repository_file: RepositoryFile, compilation_unit: CompilationUnit | None
    ) -> SourceAnalysisResult:
        scope = _AnalysisScope.build(repository_file, compilation_unit)
        if repository_file.kind not in {FileKind.C_SOURCE, FileKind.C_HEADER}:
            return scope.result(
                SourceAnalysisStatus.FAILED,
                diagnostics=(
                    _diagnostic(
                        "Only C source and header files are supported by this parser.",
                        repository_file,
                    ),
                ),
            )

        try:
            source = Path(repository_file.absolute_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as error:
            return scope.result(
                SourceAnalysisStatus.FAILED,
                diagnostics=(
                    _diagnostic(
                        "The source file could not be read.",
                        repository_file,
                        technical_details=str(error),
                    ),
                ),
            )

        locations = _Locations(source, repository_file.relative_path)
        masked_result = mask_c_non_code(source)
        diagnostics = [
            _issue_diagnostic(issue, repository_file, locations)
            for issue in masked_result.issues
        ]
        directives = _directives(source, masked_result.text)
        blanked = _blank_directive_regions(masked_result.text, directives)

        symbols: list[SourceSymbol] = []
        relationships: list[SourceRelationship] = []
        preprocessor_symbols, preprocessor_relationships, preprocessor_diagnostics = (
            _parse_directives(
                directives,
                repository_file,
                compilation_unit,
                locations,
            )
        )
        symbols.extend(preprocessor_symbols)
        relationships.extend(preprocessor_relationships)
        diagnostics.extend(preprocessor_diagnostics)

        constructs, construct_issues = _top_level_constructs(blanked)
        diagnostics.extend(
            _diagnostic(
                issue.message,
                repository_file,
                location=locations.location(issue.start, issue.end),
            )
            for issue in construct_issues
        )
        for construct in constructs:
            construct_symbols, construct_diagnostics = _construct_outputs(
                construct,
                source,
                blanked,
                repository_file,
                compilation_unit,
                locations,
            )
            symbols.extend(construct_symbols)
            diagnostics.extend(construct_diagnostics)

        status = (
            SourceAnalysisStatus.DEGRADED
            if diagnostics
            else SourceAnalysisStatus.COMPLETED
        )
        return scope.result(
            status, tuple(symbols), tuple(relationships), tuple(diagnostics)
        )


def _blank_directive_regions(masked: str, directives: tuple[_Directive, ...]) -> str:
    code = list(masked)
    for directive in directives:
        for index in range(directive.start, directive.end):
            if code[index] not in {"\n", "\r"}:
                code[index] = " "
    return "".join(code)


def _construct_outputs(
    construct: _Construct,
    source: str,
    blanked: str,
    repository_file: RepositoryFile,
    compilation_unit: CompilationUnit | None,
    locations: _Locations,
) -> tuple[list[SourceSymbol], list[Diagnostic]]:
    text = source[construct.start : construct.end]
    masked_text = blanked[construct.start : construct.end]
    symbols: list[SourceSymbol] = []
    diagnostics: list[Diagnostic] = []

    if construct.kind == "function":
        header_end = construct.header_end or construct.end
        header = _function_header(blanked[construct.start:header_end])
        if header is None:
            diagnostics.append(
                _diagnostic(
                    "A function-like definition could not be parsed conservatively.",
                    repository_file,
                    location=locations.location(construct.start, header_end),
                )
            )
            return symbols, diagnostics
        symbols.append(
            _function_symbol(
                header,
                repository_file,
                compilation_unit,
                locations,
                construct.start,
                construct.end,
                is_definition=True,
            )
        )
        diagnostics.extend(
            _parameter_diagnostics(
                header, repository_file, locations, construct.start, header_end
            )
        )
        return symbols, diagnostics

    declaration = masked_text.rstrip()
    if declaration.endswith(";"):
        declaration = declaration[:-1].rstrip()
    function = _function_header(declaration)
    if function is not None:
        symbols.append(
            _function_symbol(
                function,
                repository_file,
                compilation_unit,
                locations,
                construct.start,
                construct.end,
                is_definition=False,
            )
        )
        diagnostics.extend(
            _parameter_diagnostics(
                function,
                repository_file,
                locations,
                construct.start,
                construct.end,
            )
        )
        return symbols, diagnostics

    type_symbols, type_diagnostics = _type_symbols(
        text,
        masked_text,
        construct.start,
        repository_file,
        compilation_unit,
        locations,
    )
    symbols.extend(type_symbols)
    diagnostics.extend(type_diagnostics)
    variable, variable_diagnostic = _variable_symbol(
        text,
        masked_text,
        construct.start,
        repository_file,
        compilation_unit,
        locations,
    )
    if variable is not None:
        symbols.append(variable)
    if variable_diagnostic is not None:
        diagnostics.append(variable_diagnostic)
    return symbols, diagnostics


def _directives(source: str, masked: str) -> tuple[_Directive, ...]:
    lines = source.splitlines(keepends=True)
    masked_lines = masked.splitlines(keepends=True)
    results: list[_Directive] = []
    offset = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        masked_line = masked_lines[index]
        if not re.match(r"^[ \t]*#", masked_line):
            offset += len(line)
            index += 1
            continue
        start = offset
        parts = [line]
        offset += len(line)
        while _continues(parts[-1]) and index + 1 < len(lines):
            index += 1
            parts.append(lines[index])
            offset += len(lines[index])
        text = re.sub(r"\\\r?\n", " ", "".join(parts))
        results.append(_Directive(text=text, start=start, end=offset))
        index += 1
    return tuple(results)


def _continues(line: str) -> bool:
    return line.rstrip("\r\n").endswith("\\")


def _parse_directives(
    directives: tuple[_Directive, ...],
    repository_file: RepositoryFile,
    compilation_unit: CompilationUnit | None,
    locations: _Locations,
) -> tuple[list[SourceSymbol], list[SourceRelationship], list[Diagnostic]]:
    symbols: list[SourceSymbol] = []
    relationships: list[SourceRelationship] = []
    diagnostics: list[Diagnostic] = []
    scope = compilation_unit.id if compilation_unit else "unconfigured"
    for directive in directives:
        value = directive.text.strip()
        include = re.match(r"#\s*include\s*([<\"])([^>\"]+)[>\"]", value)
        if include:
            spelling = include.group(2).strip()
            location = locations.location(directive.start, directive.end)
            relationships.append(
                IncludeRelationship(
                    id=stable_id(
                        "include",
                        repository_file.id,
                        scope,
                        spelling,
                        str(directive.start),
                    ),
                    source_file_id=repository_file.id,
                    included_spelling=spelling,
                    resolved_file_id=None,
                    evidence=(
                        RelationshipEvidence(
                            kind=EvidenceKind.EXTRACTED_FACT,
                            description="Preprocessor include directive.",
                            location=location,
                            provenance=PARSER_NAME,
                        ),
                    ),
                    confidence=1.0,
                )
            )
            continue

        define = re.match(
            rf"#\s*define[ \t]+({_IDENTIFIER})(\(([^)]*)\))?[ \t]*(.*)",
            value,
            re.DOTALL,
        )
        if define:
            name = define.group(1)
            function_like = define.group(2) is not None
            raw_parameters = define.group(3) or ""
            parameters = tuple(
                item.strip() for item in raw_parameters.split(",") if item.strip()
            )
            replacement = define.group(4).strip() or None
            location = locations.location(directive.start, directive.end)
            evidence_kind = (
                EvidenceKind.HEURISTIC_RESULT
                if function_like and any(item == "..." or item.endswith("...") for item in parameters)
                else EvidenceKind.EXTRACTED_FACT
            )
            symbols.append(
                MacroSymbol(
                    id=stable_id(
                        "macro",
                        repository_file.id,
                        scope,
                        name,
                        str(directive.start),
                    ),
                    name=name,
                    location=location,
                    replacement=replacement,
                    confidence=(
                        _MACRO_HEURISTIC_CONFIDENCE
                        if evidence_kind is EvidenceKind.HEURISTIC_RESULT
                        else _EXACT_CONFIDENCE
                    ),
                    is_function_like=function_like,
                    parameters=parameters,
                    evidence=(
                        RelationshipEvidence(
                            kind=evidence_kind,
                            description="Preprocessor macro definition.",
                            location=location,
                            provenance=PARSER_NAME,
                        ),
                    ),
                )
            )
            if evidence_kind is EvidenceKind.HEURISTIC_RESULT:
                diagnostics.append(
                    _diagnostic(
                        "Variadic macro parameters are retained but not interpreted.",
                        repository_file,
                        location=location,
                    )
                )
            continue

        if re.match(r"#\s*(if|ifdef|ifndef|elif)\b", value):
            diagnostics.append(
                _diagnostic(
                    "Conditional preprocessing is not evaluated by the conservative parser.",
                    repository_file,
                    location=locations.location(directive.start, directive.end),
                )
            )
    return symbols, relationships, diagnostics


def _top_level_constructs(
    source: str,
) -> tuple[tuple[_Construct, ...], tuple[_ConstructIssue, ...]]:
    constructs: list[_Construct] = []
    issues: list[_ConstructIssue] = []
    segment_start = 0
    brace_depth = 0
    index = 0
    while index < len(source):
        character = source[index]
        if character == "{" and brace_depth == 0:
            header_start = _first_nonspace(source, segment_start, index)
            header = source[header_start:index]
            if _function_header(header) is not None:
                closing = _matching_brace(source, index)
                if closing is None:
                    issues.append(
                        _ConstructIssue(
                            "Unmatched function body brace.", index, len(source)
                        )
                    )
                    break
                constructs.append(
                    _Construct(
                        kind="function",
                        start=header_start,
                        end=closing + 1,
                        header_end=index,
                    )
                )
                index = closing + 1
                segment_start = index
                continue
            brace_depth = 1
        elif character == "{" and brace_depth > 0:
            brace_depth += 1
        elif character == "}" and brace_depth > 0:
            brace_depth -= 1
        elif character == "}" and brace_depth == 0:
            issues.append(_ConstructIssue("Unmatched closing brace.", index, index + 1))
            segment_start = index + 1
        elif character == ";" and brace_depth == 0:
            start = _first_nonspace(source, segment_start, index + 1)
            if start < index + 1:
                constructs.append(
                    _Construct(kind="declaration", start=start, end=index + 1)
                )
            segment_start = index + 1
        index += 1
    if brace_depth:
        issues.append(
            _ConstructIssue("Unmatched top-level brace.", segment_start, len(source))
        )
    trailing = source[segment_start:].strip()
    if trailing:
        start = _first_nonspace(source, segment_start, len(source))
        issues.append(
            _ConstructIssue(
                "Unterminated or unsupported top-level declaration.",
                start,
                len(source),
            )
        )
    return tuple(constructs), tuple(issues)


def _matching_brace(source: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _first_nonspace(source: str, start: int, end: int) -> int:
    while start < end and source[start].isspace():
        start += 1
    return start


def _function_header(value: str) -> _FunctionHeader | None:
    text = value.strip()
    if not text.endswith(")") or "=" in text or text.startswith("typedef "):
        return None
    opening = _matching_open_parenthesis(text, len(text) - 1)
    if opening is None:
        return None
    before = text[:opening].rstrip()
    name_match = re.search(rf"({_IDENTIFIER})$", before)
    if name_match is None:
        return None
    name = name_match.group(1)
    if name in _CONTROL_NAMES:
        return None
    prefix = before[: name_match.start()].strip()
    if not prefix or prefix.endswith((")", "]")) or "(*" in prefix.replace(" ", ""):
        return None
    return_type = _without_storage(prefix)
    if not return_type:
        return None
    parameter_text = text[opening + 1 : -1]
    parameters = _split_parameters(parameter_text)
    if parameters is None:
        return None
    if parameters == ("void",):
        parameters = ()
    return _FunctionHeader(
        name=name,
        name_offset=name_match.start(),
        return_type=return_type,
        parameters=parameters,
        linkage=Linkage.INTERNAL if _has_word(prefix, "static") else Linkage.EXTERNAL,
    )


def _matching_open_parenthesis(value: str, closing: int) -> int | None:
    depth = 0
    for index in range(closing, -1, -1):
        if value[index] == ")":
            depth += 1
        elif value[index] == "(":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_parameters(value: str) -> tuple[str, ...] | None:
    if not value.strip():
        return ()
    depths = _BracketDepths()
    results: list[str] = []
    start = 0
    for index, character in enumerate(value):
        depths.feed(character)
        if character == "," and not depths.nested:
            results.append(_normalize_space(value[start:index]))
            start = index + 1
    if not depths.balanced:
        return None
    results.append(_normalize_space(value[start:]))
    return tuple(item for item in results if item)


def _function_symbol(
    header: _FunctionHeader,
    repository_file: RepositoryFile,
    compilation_unit: CompilationUnit | None,
    locations: _Locations,
    start: int,
    end: int,
    *,
    is_definition: bool,
) -> FunctionSymbol:
    scope = compilation_unit.id if compilation_unit else "unconfigured"
    location = locations.location(start, end)
    return FunctionSymbol(
        id=stable_id(
            "function",
            repository_file.id,
            scope,
            header.name,
            str(start),
            "definition" if is_definition else "declaration",
        ),
        name=header.name,
        location=location,
        is_definition=is_definition,
        linkage=header.linkage,
        return_type=header.return_type,
        parameters=header.parameters,
        confidence=(
            _FUNCTION_DEFINITION_CONFIDENCE
            if is_definition
            else _FUNCTION_DECLARATION_CONFIDENCE
        ),
        evidence=(
            RelationshipEvidence(
                kind=EvidenceKind.HEURISTIC_RESULT,
                description=(
                    "Conservative function definition syntax."
                    if is_definition
                    else "Conservative function declaration syntax."
                ),
                location=location,
                provenance=PARSER_NAME,
            ),
        ),
    )


def _parameter_diagnostics(
    header: _FunctionHeader,
    repository_file: RepositoryFile,
    locations: _Locations,
    start: int,
    end: int,
) -> tuple[Diagnostic, ...]:
    if any(parameter == "..." for parameter in header.parameters):
        return (
            _diagnostic(
                "Variadic function parameters are retained but not interpreted.",
                repository_file,
                location=locations.location(start, end),
            ),
        )
    untyped = [
        parameter
        for parameter in header.parameters
        if re.fullmatch(_IDENTIFIER, parameter)
    ]
    if untyped:
        return (
            _diagnostic(
                "Old-style or untyped function parameters are ambiguous.",
                repository_file,
                location=locations.location(start, end),
            ),
        )
    return ()


def _type_symbols(
    original: str,
    masked: str,
    base_offset: int,
    repository_file: RepositoryFile,
    compilation_unit: CompilationUnit | None,
    locations: _Locations,
) -> tuple[list[TypeSymbol], list[Diagnostic]]:
    symbols: list[TypeSymbol] = []
    diagnostics: list[Diagnostic] = []
    scope = compilation_unit.id if compilation_unit else "unconfigured"
    tag_match = re.match(
        rf"\s*(?:(typedef)\s+)?(struct|union|enum)\s+({_IDENTIFIER})", masked
    )
    if tag_match is not None and (
        tag_match.group(1) is None or re.match(r"\s*\{", masked[tag_match.end() :])
    ):
        kind, name = tag_match.group(2), tag_match.group(3)
        definition = bool(re.match(r"\s*\{", masked[tag_match.end() :]))
        location = locations.location(
            base_offset + tag_match.start(), base_offset + tag_match.end()
        )
        symbols.append(
            TypeSymbol(
                id=stable_id(
                    "type",
                    repository_file.id,
                    scope,
                    kind,
                    name,
                    str(base_offset + tag_match.start()),
                ),
                name=name,
                type_kind=kind,
                location=location,
                is_definition=definition,
                confidence=_TAGGED_TYPE_CONFIDENCE,
                evidence=(
                    RelationshipEvidence(
                        kind=EvidenceKind.HEURISTIC_RESULT,
                        description=f"Named {kind} declaration.",
                        location=location,
                        provenance=PARSER_NAME,
                    ),
                ),
            )
        )

    stripped = masked.strip().rstrip(";").strip()
    if not stripped.startswith("typedef "):
        return symbols, diagnostics
    alias_match = re.search(rf"\(\s*\*\s*({_IDENTIFIER})\s*\)", stripped)
    if alias_match is None:
        alias_match = re.search(rf"({_IDENTIFIER})\s*(?:\[[^\]]*\]\s*)?$", stripped)
    if alias_match is None:
        diagnostics.append(
            _diagnostic(
                "A typedef alias could not be identified conservatively.",
                repository_file,
                location=locations.location(base_offset, base_offset + len(original)),
            )
        )
        return symbols, diagnostics
    alias = alias_match.group(1)
    absolute_start = base_offset + alias_match.start(1)
    location = locations.location(absolute_start, absolute_start + len(alias))
    underlying = _normalize_space(
        (
            stripped[: alias_match.start(1)]
            + stripped[alias_match.end(1) :]
        ).removeprefix("typedef ")
    )
    symbols.append(
        TypeSymbol(
            id=stable_id(
                "type",
                repository_file.id,
                scope,
                "typedef",
                alias,
                str(absolute_start),
            ),
            name=alias,
            type_kind="typedef",
            location=location,
            is_definition=True,
            confidence=_TYPEDEF_CONFIDENCE,
            underlying_type=underlying or None,
            evidence=(
                RelationshipEvidence(
                    kind=EvidenceKind.HEURISTIC_RESULT,
                    description="Conservative typedef declaration.",
                    location=location,
                    provenance=PARSER_NAME,
                ),
            ),
        )
    )
    return symbols, diagnostics


def _variable_symbol(
    original: str,
    masked: str,
    base_offset: int,
    repository_file: RepositoryFile,
    compilation_unit: CompilationUnit | None,
    locations: _Locations,
) -> tuple[VariableSymbol | None, Diagnostic | None]:
    stripped = masked.strip().rstrip(";").strip()
    if (
        not stripped
        or stripped.startswith("typedef ")
        or re.fullmatch(rf"(?:struct|union|enum)\s+{_IDENTIFIER}", stripped)
    ):
        return None, None
    if "{" in stripped or "}" in stripped:
        return None, None
    if _top_level_contains(stripped, ","):
        return None, _diagnostic(
            "Multiple file-scope declarators are not split conservatively.",
            repository_file,
            location=locations.location(base_offset, base_offset + len(original)),
        )
    declarator = _before_top_level_assignment(stripped)
    compact = declarator.replace(" ", "")
    if "(*" in compact:
        return None, _diagnostic(
            "Function-pointer variables are retained as unsupported syntax.",
            repository_file,
            location=locations.location(base_offset, base_offset + len(original)),
        )
    if "(" in declarator or ")" in declarator:
        return None, None
    match = re.fullmatch(
        rf"(?s)(.+?)(?P<name>{_IDENTIFIER})\s*(?P<arrays>(?:\[[^\]]*\]\s*)*)",
        declarator,
    )
    if match is None:
        return None, None
    prefix = match.group(1).strip()
    name = match.group("name")
    if not prefix or prefix.endswith((".", "->")):
        return None, None
    type_spelling = _without_storage(
        _normalize_space(f"{prefix} {match.group('arrays').strip()}")
    )
    if not type_spelling:
        return None, None
    relative_name = masked.find(name)
    absolute_name = base_offset + max(0, relative_name)
    location = locations.location(base_offset, base_offset + len(original))
    linkage = Linkage.INTERNAL if _has_word(prefix, "static") else Linkage.EXTERNAL
    is_definition = not _has_word(prefix, "extern")
    scope = compilation_unit.id if compilation_unit else "unconfigured"
    return (
        VariableSymbol(
            id=stable_id(
                "variable",
                repository_file.id,
                scope,
                name,
                str(absolute_name),
                "definition" if is_definition else "declaration",
            ),
            name=name,
            location=location,
            type_spelling=type_spelling,
            linkage=linkage,
            is_definition=is_definition,
            confidence=_VARIABLE_CONFIDENCE,
            evidence=(
                RelationshipEvidence(
                    kind=EvidenceKind.HEURISTIC_RESULT,
                    description="Conservative file-scope variable declaration.",
                    location=location,
                    provenance=PARSER_NAME,
                ),
            ),
        ),
        None,
    )


def _before_top_level_assignment(value: str) -> str:
    depths = _BracketDepths()
    for index, character in enumerate(value):
        depths.feed(character)
        if character == "=" and not depths.nested:
            return value[:index].rstrip()
    return value


def _top_level_contains(value: str, target: str) -> bool:
    depths = _BracketDepths()
    for character in value:
        depths.feed(character)
        if character == target and not depths.nested:
            return True
    return False


class _BracketDepths:
    """Tracks (), [], {} nesting while scanning one declaration.

    ``nested`` reports whether any bracket is currently open. ``balanced``
    additionally requires that no closer ever appeared without a matching
    opener and that nothing was left open. Callers that tolerate stray
    closers simply ignore ``balanced``.
    """

    __slots__ = ("_depths", "_unbalanced")

    def __init__(self) -> None:
        self._depths = {"(": 0, "[": 0, "{": 0}
        self._unbalanced = False

    def feed(self, character: str) -> None:
        if character in self._depths:
            self._depths[character] += 1
        elif character in {")", "]", "}"}:
            opener = {")": "(", "]": "[", "}": "{"}[character]
            if self._depths[opener]:
                self._depths[opener] -= 1
            else:
                self._unbalanced = True

    @property
    def nested(self) -> bool:
        return any(self._depths.values())

    @property
    def balanced(self) -> bool:
        return not self._unbalanced and not self.nested


def _without_storage(value: str) -> str:
    words = _normalize_space(value).split()
    return " ".join(word for word in words if word not in _STORAGE_WORDS)


def _has_word(value: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", value))


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _diagnostic(
    message: str,
    repository_file: RepositoryFile,
    *,
    technical_details: str = "",
    location: SourceLocation | None = None,
) -> Diagnostic:
    metadata = {}
    if location is not None:
        metadata = {
            "line": str(location.line),
            "column": str(location.column),
            "end_line": str(location.end_line or location.line),
            "end_column": str(location.end_column or location.column),
        }
    return Diagnostic(
        code=DiagnosticCode.CONSERVATIVE_PARSE_LIMITATION,
        severity=DiagnosticSeverity.WARNING,
        message=message,
        technical_details=technical_details,
        missing_capability="complete_c_semantics",
        recoverability=Recoverability.REDUCED_CAPABILITY,
        suggested_actions=(
            "Review the source range and treat omitted findings as unavailable.",
        ),
        related_paths=(repository_file.absolute_path,),
        metadata=metadata,
    )


def _issue_diagnostic(
    issue: MaskIssue,
    repository_file: RepositoryFile,
    locations: _Locations,
) -> Diagnostic:
    return _diagnostic(
        issue.message,
        repository_file,
        location=locations.location(issue.offset, issue.end_offset),
    )


def _deduplicate_symbols(symbols: list[SourceSymbol]) -> list[SourceSymbol]:
    return list({item.id: item for item in symbols}.values())


def _deduplicate_relationships(
    relationships: list[SourceRelationship],
) -> list[SourceRelationship]:
    return list({item.id: item for item in relationships}.values())


def _deduplicate_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    results: dict[tuple[object, ...], Diagnostic] = {}
    for item in diagnostics:
        key = (
            item.code,
            item.message,
            item.related_paths,
            tuple(sorted(item.metadata.items())),
        )
        results.setdefault(key, item)
    return list(results.values())
