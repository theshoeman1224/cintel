from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from cintel.application.initialization import InitializationResult
from cintel.domain.models import DoctorReport


def render_initialization(result: InitializationResult, as_json: bool = False) -> str:
    if as_json:
        return _json(result)
    lines = [
        f"Initialized Legacy C Code Intelligence for {result.repository.root}",
        f"Configuration: {result.config.output_directory}/config.toml",
        f"Database: {result.config.database_path}",
    ]
    if result.created_paths:
        lines.append(f"Created {len(result.created_paths)} path(s).")
    if result.existing_paths:
        lines.append(f"Reused {len(result.existing_paths)} existing path(s).")
    lines.append("Next: run `cintel --repository <path> doctor`.")
    return "\n".join(lines)


def render_doctor(report: DoctorReport, as_json: bool = False) -> str:
    if as_json:
        return _json(report)
    lines = [
        "Legacy C Code Intelligence doctor",
        f"Repository: {report.repository_root}",
        f"Python: {report.python_version}",
        f"Output writable: {'yes' if report.output_directory_writable else 'no'}",
        "",
        "Tools:",
    ]
    for tool in report.tools:
        state = "available" if tool.available else "unavailable"
        version = f" — {tool.version}" if tool.version else ""
        lines.append(f"  {tool.name}: {state}{version}")
    lines.extend(("", "Detected inputs:"))
    for name, paths in report.detected_inputs.items():
        lines.append(f"  {name}: {len(paths)}")
        lines.extend(f"    {path}" for path in paths[:10])
        if len(paths) > 10:
            lines.append(f"    … {len(paths) - 10} more")
    lines.extend(("", "Capabilities:"))
    for capability in report.capabilities:
        lines.append(f"  {capability.name}: {capability.status.value} — {capability.reason}")
    if report.diagnostics:
        lines.extend(("", "Diagnostics:"))
        for diagnostic in report.diagnostics:
            lines.append(
                f"  [{diagnostic.code}] {diagnostic.severity.value}: {diagnostic.message}"
            )
            lines.extend(f"    Action: {action}" for action in diagnostic.suggested_actions)
    lines.extend(("", "Recommended next actions:"))
    lines.extend(f"  - {action}" for action in report.recommended_actions)
    return "\n".join(lines)


def _json(value: Any) -> str:
    return json.dumps(asdict(value), default=_json_default, indent=2, sort_keys=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")
