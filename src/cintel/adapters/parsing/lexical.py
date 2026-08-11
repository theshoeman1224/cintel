"""Small lexical helpers for conservative C source inspection.

This is deliberately not a C lexer.  It only masks regions that must not be
mistaken for declarations while preserving every character offset and newline.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    issues: list[MaskIssue] = []
    state = "code"
    start = 0
    index = 0

    def blank(position: int) -> None:
        if masked[position] not in {"\n", "\r"}:
            masked[position] = " "

    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if state == "code":
            if character == "/" and following == "/":
                state = "line_comment"
                start = index
                blank(index)
                blank(index + 1)
                index += 2
                continue
            if character == "/" and following == "*":
                state = "block_comment"
                start = index
                blank(index)
                blank(index + 1)
                index += 2
                continue
            if character == '"':
                state = "string"
                start = index
                blank(index)
                index += 1
                continue
            if character == "'":
                state = "character"
                start = index
                blank(index)
                index += 1
                continue
            index += 1
            continue

        if state == "line_comment":
            if character in {"\n", "\r"}:
                state = "code"
            else:
                blank(index)
            index += 1
            continue

        if state == "block_comment":
            if character == "*" and following == "/":
                blank(index)
                blank(index + 1)
                state = "code"
                index += 2
                continue
            blank(index)
            index += 1
            continue

        delimiter = '"' if state == "string" else "'"
        if character == "\\":
            blank(index)
            if index + 1 < len(source):
                blank(index + 1)
                index += 2
            else:
                index += 1
            continue
        if character == delimiter:
            blank(index)
            state = "code"
            index += 1
            continue
        if character in {"\n", "\r"}:
            issues.append(
                MaskIssue(
                    message=f"Unterminated {state} literal.",
                    offset=start,
                    end_offset=index,
                )
            )
            state = "code"
            index += 1
            continue
        blank(index)
        index += 1

    if state == "block_comment":
        issues.append(
            MaskIssue(
                message="Unterminated block comment.",
                offset=start,
                end_offset=len(source),
            )
        )
    elif state in {"string", "character"}:
        issues.append(
            MaskIssue(
                message=f"Unterminated {state} literal.",
                offset=start,
                end_offset=len(source),
            )
        )

    result = "".join(masked)
    if len(result) != len(source) or result.count("\n") != source.count("\n"):
        raise AssertionError("C masking must preserve offsets and line numbers")
    return MaskedCSource(text=result, issues=tuple(issues))
