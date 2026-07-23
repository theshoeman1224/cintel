from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Sequence

from cintel.application import parse_assignments
from cintel.cli.presentation import (
    render_build_discovery,
    render_compilation_units,
    render_doctor,
    render_initialization,
    render_scan,
)
from cintel.composition import create_application
from cintel.configuration.loader import default_config, load_config
from cintel.domain.errors import CintelError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cintel",
        description="Offline-first intelligence for legacy C repositories.",
    )
    parser.add_argument("--repository", type=Path, help="Repository root")
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    parser.add_argument("--output-directory", type=Path, help="Generated-output directory")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Render machine-readable output")
    parser.add_argument("--makefile", type=Path)
    parser.add_argument("--make-working-directory", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--make-var", action="append", default=[], metavar="NAME=value")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=value")
    parser.add_argument("--build-config", default="default")
    parser.add_argument("--force-build-discovery", action="store_true")
    parser.add_argument("--respect-make-timestamps", action="store_true")
    parser.add_argument("--input-file", type=Path)

    subcommands = parser.add_subparsers(dest="command", required=True)
    initialize = subcommands.add_parser(
        "init", help="Create a local .code-intelligence workspace"
    )
    initialize.add_argument("repository_path", type=Path)
    subcommands.add_parser("doctor", help="Inspect tools, inputs, and capabilities")
    subcommands.add_parser(
        "scan", help="Inventory C sources, headers, and Make build inputs"
    )
    build = subcommands.add_parser("build", help="Discover and inspect selected builds")
    build_commands = build.add_subparsers(dest="build_command", required=True)
    build_commands.add_parser("discover", help="Run and parse a GNU Make dry-run")
    build_commands.add_parser("units", help="List discovered compilation units")
    build_show = build_commands.add_parser(
        "show", help="Show compilation units for a source file"
    )
    build_show.add_argument("source_file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = create_application()
    try:
        if args.command == "init":
            result = app.initialization.initialize(
                args.repository_path,
                app.storage_factory,
                args.output_directory,
            )
            print(render_initialization(result, args.json))
            return 0

        if args.command == "doctor":
            config = _resolve_config(args.config, args.repository, args.output_directory)
            report = app.doctor.inspect(config)
            print(render_doctor(report, args.json))
            return 2 if any(item.severity.value == "error" for item in report.diagnostics) else 0

        if args.command == "scan":
            config = _resolve_config(args.config, args.repository, args.output_directory)
            result = app.scanning.scan(config)
            print(render_scan(result, args.json))
            return (
                2
                if any(
                    item.severity.value == "error" for item in result.scan.diagnostics
                )
                else 0
            )

        if args.command == "build":
            config = _resolve_config(args.config, args.repository, args.output_directory)
            if args.build_command == "discover":
                if args.input_file is not None:
                    from cintel.domain.errors import FeatureNotImplementedError

                    raise FeatureNotImplementedError(
                        "Saved Make-output importing belongs to Phase 4 guided recovery."
                    )
                configuration = app.build_discovery.create_configuration(
                    config,
                    makefile=args.makefile,
                    working_directory=args.make_working_directory,
                    target=args.target,
                    make_variables=parse_assignments(args.make_var, "--make-var"),
                    environment_overrides=parse_assignments(args.env, "--env"),
                    name=args.build_config,
                    respect_make_timestamps=args.respect_make_timestamps,
                )
                preview = app.build_discovery.preview(configuration)
                if args.verbose or (
                    not args.non_interactive and sys.stdin.isatty()
                ):
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
                if not args.non_interactive and sys.stdin.isatty():
                    answer = input("Proceed with Makefile evaluation? [y/N] ")
                    if answer.strip().lower() not in {"y", "yes"}:
                        print("Build discovery cancelled.", file=sys.stderr)
                        return 2
                result = app.build_discovery.discover(
                    config, configuration, force=args.force_build_discovery
                )
                print(render_build_discovery(result, args.json))
                return (
                    2
                    if any(
                        item.severity.value == "error"
                        for item in result.diagnostics
                    )
                    else 0
                )
            if args.build_command == "units":
                units = app.build_discovery.list_units(config, args.build_config)
                print(render_compilation_units(units, args.json))
                return 0
            if args.build_command == "show":
                units = app.build_discovery.show_source(
                    config, args.source_file, args.build_config
                )
                print(render_compilation_units(units, args.json))
                return 0 if units else 1

        parser.error(f"Unsupported command: {args.command}")
    except CintelError as exc:
        print(f"cintel: {exc}", file=sys.stderr)
        return 2
    return 2


def _resolve_config(
    config_path: Path | None,
    repository: Path | None,
    output_directory: Path | None,
):
    if config_path is not None:
        return load_config(config_path.expanduser().resolve())
    root = (repository or Path.cwd()).expanduser().resolve()
    conventional = root / ".code-intelligence" / "config.toml"
    if conventional.is_file() and output_directory is None:
        return load_config(conventional)
    return default_config(root, output_directory)


def _redacted_command_preview(
    arguments: tuple[str, ...],
    environment_overrides: tuple[tuple[str, str], ...] = (),
) -> str:
    redacted = [
        f"{name}={value}" for name, value in environment_overrides
    ] + list(arguments)
    secret_markers = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "KEY", "CREDENTIAL", "AUTH")
    for index, argument in enumerate(redacted):
        if "=" not in argument:
            continue
        name, _ = argument.split("=", 1)
        if any(marker in name.upper() for marker in secret_markers):
            redacted[index] = f"{name}=***REDACTED***"
    return shlex.join(redacted)


if __name__ == "__main__":
    raise SystemExit(main())
