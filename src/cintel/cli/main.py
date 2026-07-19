from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from cintel.cli.presentation import render_doctor, render_initialization, render_scan
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

    subcommands = parser.add_subparsers(dest="command", required=True)
    initialize = subcommands.add_parser(
        "init", help="Create a local .code-intelligence workspace"
    )
    initialize.add_argument("repository_path", type=Path)
    subcommands.add_parser("doctor", help="Inspect tools, inputs, and capabilities")
    subcommands.add_parser(
        "scan", help="Inventory C sources, headers, and Make build inputs"
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
