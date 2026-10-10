"""Subprocess execution contract.

Only the command-runner adapter may import subprocess; everything else asks
this protocol to run an argument list with shell=False.
"""

from typing import Protocol

from cintel.domain.models import CommandRequest, CommandResult


class CommandRunner(Protocol):
    """Run one non-interactive command and capture its result."""

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute the request and return exit code, output, and duration."""
        ...
