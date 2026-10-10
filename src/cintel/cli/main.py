from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import replace
from enum import IntEnum
from pathlib import Path

from cintel.application import parse_assignments, parse_path_placeholders
from cintel.application.queries import FunctionCandidates, FunctionNotFound
from cintel.cli.presentation import (
    render_analysis,
    render_build_discovery,
    render_call_sites,
    render_compilation_units,
    render_context_result,
    render_doctor,
    render_function_detail,
    render_initialization,
    render_recovery,
    render_report_run,
    render_scan,
    render_symbols,
)
from cintel.composition import create_application
from cintel.configuration.loader import default_config, load_config
from cintel.domain.errors import CintelError, ConfigurationError
from cintel.domain.models import InputArtifactType, WorkflowStatus
from cintel.utilities.secrets import redact_assignment_arguments


class ExitCode(IntEnum):
    SUCCESS = 0
    NO_MATCH = 1
    FAILURE = 2


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cintel",
        description="Offline-first intelligence for legacy C repositories.",
        epilog=(
            "Global options such as --repository and --config must come before "
            "the subcommand, for example: cintel --repository ./src scan. "
            "Run 'cintel <command> --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repository",
        type=Path,
        help="Repository root; defaults to the current directory",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.toml; overrides --repository and --output-directory",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Generated-output directory; overrides the configured location",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt before Makefile evaluation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress detail to standard error",
    )
    parser.add_argument("--json", action="store_true", help="Render machine-readable output")
    parser.add_argument(
        "--makefile", type=Path, help="Makefile path relative to the working directory"
    )
    parser.add_argument(
        "--make-working-directory", type=Path, help="Directory where Make runs"
    )
    parser.add_argument(
        "--target", help="Make target to evaluate; defaults to the Makefile default"
    )
    parser.add_argument(
        "--make-var",
        action="append",
        default=[],
        metavar="NAME=value",
        help="Make variable assignment; repeatable",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=value",
        help="Environment override for the Make run; repeatable",
    )
    parser.add_argument(
        "--build-config",
        default="default",
        help="Named build configuration (default: default)",
    )
    parser.add_argument(
        "--force-build-discovery",
        action="store_true",
        help="Ignore a matching cached discovery result",
    )
    parser.add_argument(
        "--respect-make-timestamps",
        action="store_true",
        help="Omit -B so Make respects existing file timestamps",
    )
    parser.add_argument(
        "--input-file", type=Path, help="Evidence file to validate and import"
    )
    parser.add_argument(
        "--input-type",
        choices=[item.value for item in InputArtifactType],
        default=InputArtifactType.MAKE_DRY_RUN.value,
        help="Type of evidence supplied with --input-file",
    )
    parser.add_argument(
        "--path-placeholder",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help=(
            "Replace OLD with NEW when reading an imported Make dry-run "
            "before parsing; repeatable"
        ),
    )

    subcommands = parser.add_subparsers(dest="command", required=True)
    initialize = subcommands.add_parser(
        "init", help="Create a local .code-intelligence workspace"
    )
    initialize.add_argument(
        "repository_path",
        type=Path,
        nargs="?",
        help=(
            "Repository root to initialize; defaults to --repository or the "
            "current directory"
        ),
    )
    subcommands.add_parser("doctor", help="Inspect tools, inputs, and capabilities")
    subcommands.add_parser(
        "scan", help="Inventory C sources, headers, and Make build inputs"
    )
    subcommands.add_parser("setup", help="Assess missing inputs and create recovery instructions")
    subcommands.add_parser("instructions", help="Regenerate REQUIRED_INPUTS.md")
    subcommands.add_parser("resume", help="Validate supplied evidence and resume analysis")
    analyze = subcommands.add_parser(
        "analyze", help="Run conservative source analysis over scanned files"
    )
    analyze.add_argument(
        "--force-analysis",
        action="store_true",
        help="Reparse every target instead of reusing unchanged results",
    )
    build = subcommands.add_parser("build", help="Discover and inspect selected builds")
    build_commands = build.add_subparsers(dest="build_command", required=True)
    build_commands.add_parser(
        "discover",
        help="Run and parse a GNU Make dry-run",
        description=(
            "Run GNU Make with -n -B and parse the output into compilation "
            "units, or import validated evidence with --input-file."
        ),
    )
    build_commands.add_parser("units", help="List discovered compilation units")
    build_show = build_commands.add_parser(
        "show", help="Show compilation units for a source file"
    )
    build_show.add_argument("source_file", help="Repository-relative source path")
    symbols = subcommands.add_parser(
        "symbols", help="List stored symbols from source analysis"
    )
    symbols.add_argument(
        "--kind",
        choices=["function", "variable", "type", "macro"],
        help="Filter symbols by kind",
    )
    symbols.add_argument("name", nargs="?", help="Exact symbol name to filter by")
    show = subcommands.add_parser("show", help="Show details for a symbol")
    show_commands = show.add_subparsers(dest="show_command", required=True)
    show_function = show_commands.add_parser(
        "function", help="Show a function definition, callers, and callees"
    )
    show_function.add_argument("name", help="Function name to look up")
    show_function.add_argument(
        "--file",
        help="Repository-relative path that defines the function",
    )
    callers = subcommands.add_parser("callers", help="List direct callers of a function")
    callers.add_argument("name", help="Function name to look up")
    callers.add_argument(
        "--file", help="Repository-relative path that defines the function"
    )
    callees = subcommands.add_parser("callees", help="List direct callees of a function")
    callees.add_argument("name", help="Function name to look up")
    callees.add_argument(
        "--file", help="Repository-relative path that defines the function"
    )
    context = subcommands.add_parser(
        "context", help="Build a deterministic, budgeted context package"
    )
    context_commands = context.add_subparsers(dest="context_command", required=True)
    context_function = context_commands.add_parser(
        "function", help="Build a context package for a function"
    )
    context_function.add_argument("name", help="Function name to package")
    context_function.add_argument(
        "--budget",
        type=_positive_int,
        default=8000,
        help="Character budget for the package (default: 8000)",
    )
    context_function.add_argument(
        "--file", help="Repository-relative path that defines the function"
    )
    subcommands.add_parser(
        "report",
        help="Regenerate all Markdown/JSON report families from stored state",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = create_application()
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.error(f"Unsupported command: {args.command}")
        return int(ExitCode.FAILURE)
    try:
        return int(handler(app, args))
    except CintelError as exc:
        if args.json:
            print(
                json.dumps(
                    {"error": {"type": type(exc).__name__, "message": str(exc)}},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"cintel: {exc}", file=sys.stderr)
        return int(ExitCode.FAILURE)


def _run_init(app, args) -> int:
    repository = args.repository_path or args.repository or Path.cwd()
    result = app.initialization.initialize(
        repository,
        app.storage_factory,
        args.output_directory,
    )
    print(render_initialization(result, args.json))
    return ExitCode.SUCCESS


def _run_doctor(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    report = app.doctor.inspect(config)
    print(render_doctor(report, args.json))
    return _diagnostics_exit_code(report.diagnostics)


def _run_scan(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    result = app.scanning.scan(config)
    print(render_scan(result, args.json))
    return _diagnostics_exit_code(result.scan.diagnostics)


def _run_recovery(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    configuration = _create_build_configuration(app, config, args)
    if args.command == "setup":
        if args.input_file is not None:
            raise ConfigurationError(
                "cintel setup does not accept --input-file; run cintel resume "
                "to validate and import evidence."
            )
        result = app.recovery.setup(config, configuration)
    elif args.command == "instructions":
        if args.input_file is not None:
            raise ConfigurationError(
                "cintel instructions does not accept --input-file; run cintel "
                "resume to validate and import evidence."
            )
        result = app.recovery.instructions(config, configuration)
    else:
        result = app.recovery.resume(
            config,
            configuration,
            args.input_file,
            InputArtifactType(args.input_type),
            parse_path_placeholders(args.path_placeholder, "--path-placeholder"),
        )
    print(render_recovery(result, args.json))
    return (
        ExitCode.FAILURE
        if result.status is WorkflowStatus.INTERRUPTED
        else ExitCode.SUCCESS
    )


def _run_analyze(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    summary = app.analysis.analyze(
        config,
        build_configuration_name=args.build_config,
        force=args.force_analysis,
    )
    print(render_analysis(summary, args.json))
    return _diagnostics_exit_code(summary.diagnostics)


def _run_build(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    if args.build_command == "discover":
        return _run_build_discover(app, config, args)
    if args.build_command == "units":
        units = app.build_discovery.list_units(config, args.build_config)
        print(render_compilation_units(units, args.json))
        return ExitCode.SUCCESS if units else ExitCode.NO_MATCH
    if args.build_command == "show":
        units = app.build_discovery.show_source(
            config, args.source_file, args.build_config
        )
        print(render_compilation_units(units, args.json))
        return ExitCode.SUCCESS if units else ExitCode.NO_MATCH
    return ExitCode.FAILURE


def _run_build_discover(app, config, args) -> int:
    configuration = _create_build_configuration(app, config, args)
    if args.input_file is not None:
        recovery = app.recovery.resume(
            config,
            configuration,
            args.input_file,
            InputArtifactType(args.input_type),
            parse_path_placeholders(args.path_placeholder, "--path-placeholder"),
        )
        if recovery.build_result is None:
            print(render_recovery(recovery, args.json))
            return ExitCode.FAILURE
        print(render_build_discovery(recovery.build_result, args.json))
        return ExitCode.SUCCESS
    preview = app.build_discovery.preview(configuration)
    interactive = not args.non_interactive and sys.stdin.isatty()
    print(
        "Make evaluation command: "
        + _redacted_command_preview(
            preview, configuration.environment_overrides
        ),
        file=sys.stderr,
    )
    print(
        "Warning: make -n may evaluate $(shell ...) expressions.",
        file=sys.stderr,
    )
    if interactive:
        print(
            "Make evaluation command: "
            + _redacted_command_preview(
                preview, configuration.environment_overrides
            ),
            file=sys.stderr,
        )
        print(
            "Warning: make -n may evaluate $(shell ...) expressions.",
            file=sys.stderr,
        )
    if interactive:
        answer = input("Proceed with Makefile evaluation? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Build discovery cancelled.", file=sys.stderr)
            return ExitCode.FAILURE
    result = app.build_discovery.discover(
        config, configuration, force=args.force_build_discovery
    )
    print(render_build_discovery(result, args.json))
    return _diagnostics_exit_code(result.diagnostics)


def _run_symbols(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    result = app.queries.symbols(config, kind=args.kind, name=args.name)
    print(render_symbols(result, args.json))
    return ExitCode.SUCCESS if result.entries else ExitCode.NO_MATCH


def _run_show(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    if args.show_command == "function":
        result = app.queries.function(config, args.name, file=args.file)
        print(render_function_detail(result, args.json))
        if isinstance(result, (FunctionCandidates, FunctionNotFound)):
            return ExitCode.NO_MATCH
        return ExitCode.SUCCESS
    return ExitCode.FAILURE


def _run_function_query(app, args, query) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    result = query(config, args.name, file=args.file)
    if isinstance(result, (FunctionCandidates, FunctionNotFound)):
        print(render_function_detail(result, args.json))
        return ExitCode.NO_MATCH
    print(render_call_sites(args.name, result, args.json))
    return ExitCode.SUCCESS if result else ExitCode.NO_MATCH


def _run_callers(app, args) -> int:
    return _run_function_query(app, args, app.queries.callers)


def _run_callees(app, args) -> int:
    return _run_function_query(app, args, app.queries.callees)


def _run_context(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    if args.context_command == "function":
        result = app.context.context_function(
            config, args.name, file=args.file, budget=args.budget
        )
        print(render_context_result(result, args.json))
        if isinstance(result, (FunctionCandidates, FunctionNotFound)):
            return ExitCode.NO_MATCH
        return ExitCode.SUCCESS
    return ExitCode.FAILURE


def _run_report(app, args) -> int:
    config = _resolve_config(args.config, args.repository, args.output_directory)
    result = app.reports.generate_all(config)
    print(render_report_run(result, args.json))
    return _diagnostics_exit_code(result.diagnostics)


_HANDLERS = {
    "init": _run_init,
    "doctor": _run_doctor,
    "scan": _run_scan,
    "setup": _run_recovery,
    "instructions": _run_recovery,
    "resume": _run_recovery,
    "analyze": _run_analyze,
    "build": _run_build,
    "symbols": _run_symbols,
    "show": _run_show,
    "callers": _run_callers,
    "callees": _run_callees,
    "context": _run_context,
    "report": _run_report,
}


def _diagnostics_exit_code(diagnostics) -> ExitCode:
    has_error = any(item.severity.value == "error" for item in diagnostics)
    return ExitCode.FAILURE if has_error else ExitCode.SUCCESS


def _resolve_config(
    config_path: Path | None,
    repository: Path | None,
    output_directory: Path | None,
):
    if config_path is not None:
        return load_config(config_path.expanduser().resolve())
    root = (repository or Path.cwd()).expanduser().resolve()
    conventional = root / ".code-intelligence" / "config.toml"
    if conventional.is_file():
        config = load_config(conventional)
        if output_directory is None:
            return config
        resolved = output_directory.expanduser().resolve()
        return replace(
            config,
            output_directory=str(resolved),
            database_path=str(resolved / "index.sqlite"),
        )
    return default_config(root, output_directory)


def _create_build_configuration(app, config, args):
    return app.build_discovery.create_configuration(
        config,
        makefile=args.makefile,
        working_directory=args.make_working_directory,
        target=args.target,
        make_variables=parse_assignments(args.make_var, "--make-var"),
        environment_overrides=parse_assignments(args.env, "--env"),
        name=args.build_config,
        respect_make_timestamps=args.respect_make_timestamps,
    )


def _redacted_command_preview(
    arguments: tuple[str, ...],
    environment_overrides: tuple[tuple[str, str], ...] = (),
) -> str:
    arguments_with_environment = [
        f"{name}={value}" for name, value in environment_overrides
    ] + list(arguments)
    return shlex.join(redact_assignment_arguments(arguments_with_environment))


if __name__ == "__main__":
    raise SystemExit(main())
