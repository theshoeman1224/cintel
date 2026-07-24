from __future__ import annotations

import re
from collections.abc import Iterable

_SENSITIVE_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|KEY|CREDENTIAL|AUTH)(?:_|$)",
    re.IGNORECASE,
)


def is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME.search(name))


def redact_value(name: str, value: str, replacement: str) -> str:
    return replacement if is_sensitive_name(name) else value


def redact_assignment_arguments(
    arguments: Iterable[str], replacement: str = "***REDACTED***"
) -> tuple[str, ...]:
    redacted: list[str] = []
    for argument in arguments:
        if "=" in argument:
            name, _ = argument.split("=", 1)
            if is_sensitive_name(name):
                redacted.append(f"{name}={replacement}")
                continue
        redacted.append(argument)
    return tuple(redacted)
