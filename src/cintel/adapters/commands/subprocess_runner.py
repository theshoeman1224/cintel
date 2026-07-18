"""The only adapter permitted to create subprocesses."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from cintel.domain.models import CommandRequest, CommandResult, OutputDestination


class SubprocessCommandRunner:
    def run(self, request: CommandRequest) -> CommandResult:
        environment = os.environ.copy()
        environment.update(dict(request.environment_overrides))
        capture = request.output_destination is not OutputDestination.INHERIT
        started = time.monotonic()
        timed_out = False

        try:
            completed = subprocess.run(
                list(request.arguments),
                cwd=request.working_directory,
                env=environment,
                capture_output=capture,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
                shell=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = _as_text(exc.stdout)
            stderr = _as_text(exc.stderr)
            exit_code = 124
        except OSError as exc:
            stdout = ""
            stderr = str(exc)
            exit_code = 127

        duration = time.monotonic() - started
        if request.output_destination is OutputDestination.FILE:
            Path(request.output_file or "").write_text(stdout, encoding="utf-8")

        return CommandResult(
            standard_output=stdout,
            standard_error=stderr,
            exit_code=exit_code,
            duration_seconds=duration,
            executed_command=request.arguments,
            effective_working_directory=str(Path(request.working_directory).resolve()),
            timed_out=timed_out,
        )


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
