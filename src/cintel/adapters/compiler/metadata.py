from cintel.domain.models import CommandRequest, CommandRisk
from cintel.ports.commands import CommandRunner


class GCCCompilerMetadataProvider:
    """Minimal compiler identity probing needed for build fingerprints."""

    def __init__(self, command_runner: CommandRunner) -> None:
        self._command_runner = command_runner

    def version(self, executable: str, working_directory: str) -> str | None:
        result = self._command_runner.run(
            CommandRequest(
                arguments=(executable, "--version"),
                working_directory=working_directory,
                timeout_seconds=10,
                risk=CommandRisk.READ_ONLY,
            )
        )
        if result.exit_code != 0:
            return None
        output = result.standard_output.strip() or result.standard_error.strip()
        return output.splitlines()[0] if output else None
