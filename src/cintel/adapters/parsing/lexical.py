"""Small lexical helpers for conservative C source inspection.

This is deliberately not a C lexer.  It only masks regions that must not be
mistaken for declarations while preserving every character offset and newline.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MaskIssue:
    message: str
    offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class MaskedCSource:
    text: str
    issues: tuple[MaskIssue, ...]


def mask_c_non_code(source: str) -> MaskedCSource:
    """Mask comments and literals without changing source length or newlines."""

    masked = list(source)
    context = _MaskContext(masked)
    state = "code"
    index = 0

    while index < len(source):
        if state == "code":
            index, state = _mask_code(source, context, index)
        elif state == "line_comment":
            index, state = _mask_line_comment(source, context, index)
        elif state == "block_comment":
            index, state = _mask_block_comment(source, context, index)
        else:
            index, state = _mask_quoted(source, context, index, state)

    issues = [*context.issues, *_unterminated_issues(context, state, len(source))]

    result = "".join(masked)
    if len(result) != len(source) or result.count("\n") != source.count("\n"):
        raise AssertionError("C masking must preserve offsets and line numbers")
    return MaskedCSource(text=result, issues=tuple(issues))


@dataclass
class _MaskContext:
    """Mutable masking state shared by the per-state handlers."""

    masked: list[str]
    issues: list[MaskIssue] = field(default_factory=list)
    start: int = 0


def _blank(masked: list[str], position: int) -> None:
    if masked[position] not in {"\n", "\r"}:
        masked[position] = " "


def _enter(context: _MaskContext, index: int) -> None:
    context.start = index


def _mask_code(
    source: str, context: _MaskContext, index: int
) -> tuple[int, str]:
    character = source[index]
    following = source[index + 1] if index + 1 < len(source) else ""
    if character == "/" and following == "/":
        _blank(context.masked, index)
        _blank(context.masked, index + 1)
        _enter(context, index)
        return index + 2, "line_comment"
    if character == "/" and following == "*":
        _blank(context.masked, index)
        _blank(context.masked, index + 1)
        _enter(context, index)
        return index + 2, "block_comment"
    if character == '"':
        _blank(context.masked, index)
        _enter(context, index)
        return index + 1, "string"
    if character == "'":
        _blank(context.masked, index)
        _enter(context, index)
        return index + 1, "character"
    return index + 1, "code"


def _mask_line_comment(
    source: str, context: _MaskContext, index: int
) -> tuple[int, str]:
    character = source[index]
    if character in {"\n", "\r"}:
        return index + 1, "code"
    _blank(context.masked, index)
    return index + 1, "line_comment"


def _mask_block_comment(
    source: str, context: _MaskContext, index: int
) -> tuple[int, str]:
    character = source[index]
    following = source[index + 1] if index + 1 < len(source) else ""
    if character == "*" and following == "/":
        _blank(context.masked, index)
        _blank(context.masked, index + 1)
        return index + 2, "code"
    _blank(context.masked, index)
    return index + 1, "block_comment"


def _mask_quoted(
    source: str, context: _MaskContext, index: int, state: str
) -> tuple[int, str]:
    delimiter = '"' if state == "string" else "'"
    character = source[index]
    if character == "\\":
        _blank(context.masked, index)
        if index + 1 < len(source):
            _blank(context.masked, index + 1)
            return index + 2, state
        return index + 1, state
    if character == delimiter:
        _blank(context.masked, index)
        return index + 1, "code"
    if character in {"\n", "\r"}:
        context.issues.append(
            MaskIssue(
                message=f"Unterminated {state} literal.",
                offset=context.start,
                end_offset=index,
            )
        )
        return index + 1, "code"
    _blank(context.masked, index)
    return index + 1, state


def _unterminated_issues(
    context: _MaskContext, state: str, source_length: int
) -> list[MaskIssue]:
    if state == "block_comment":
        return [
            MaskIssue(
                message="Unterminated block comment.",
                offset=context.start,
                end_offset=source_length,
            )
        ]
    if state in {"string", "character"}:
        return [
            MaskIssue(
                message=f"Unterminated {state} literal.",
                offset=context.start,
                end_offset=source_length,
            )
        ]
    return []
