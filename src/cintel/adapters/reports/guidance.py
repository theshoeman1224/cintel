from __future__ import annotations

import shlex
from typing import Any

from cintel.domain.models import CommandInstruction


class MarkdownGuidanceRenderer:
    def render(self, report_name: str, data: Any) -> str:
        if report_name != "required_inputs":
            raise ValueError(f"Unsupported guidance report: {report_name}")
        instructions = tuple(data)
        lines = [
            "# Required inputs",
            "",
            "The deterministic scan can continue with reduced capabilities while these inputs are absent.",
            "Commands below are instructions only and are not executed by `cintel instructions`.",
            "",
            "## Security warnings",
            "",
            "- `make -n` may evaluate `$(shell ...)` expressions.",
            "- Real builds and generation targets may modify files.",
            "- Environment listings and build logs may contain secrets.",
            "- Preprocessed files may contain proprietary source and absolute paths.",
            "- Source must not be sent to an AI provider without explicit approval; AI is disabled by default.",
        ]
        if not instructions:
            lines.extend(("", "No additional inputs are currently required."))
        for index, item in enumerate(instructions, 1):
            if not isinstance(item, CommandInstruction):
                raise TypeError("Guidance reports require CommandInstruction values")
            lines.extend(
                (
                    "",
                    f"## {index}. {item.title}",
                    "",
                    item.reason,
                    "",
                    f"- Working directory: `{item.working_directory}`",
                    f"- Risk: `{item.risk.value}`",
                    f"- Expected output: `{item.expected_output_file or 'standard output'}`",
                    "",
                    "```bash",
                    _render_capture(item),
                    "```",
                )
            )
            if item.warnings:
                lines.extend(("", "Warnings:"))
                lines.extend(f"- {warning}" for warning in item.warnings)
            lines.extend(("", "Validation:"))
            lines.extend(f"- {step}" for step in item.validation_steps)
            lines.extend(
                (
                    "",
                    "Resume with:",
                    "",
                    "```bash",
                    shlex.join(item.resume_command),
                    "```",
                )
            )
        return "\n".join(lines) + "\n"


def _render_capture(item: CommandInstruction) -> str:
    command = shlex.join(item.arguments)
    if item.expected_output_file:
        return f"{command} > {shlex.quote(item.expected_output_file)} 2>&1"
    return command
