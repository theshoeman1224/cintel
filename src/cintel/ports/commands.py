from typing import Protocol

from cintel.domain.models import CommandRequest, CommandResult


class CommandRunner(Protocol):
    def run(self, request: CommandRequest) -> CommandResult: ...

