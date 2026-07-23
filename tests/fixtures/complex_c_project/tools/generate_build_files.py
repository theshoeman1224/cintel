#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--telemetry", required=True)
    parser.add_argument("--fast-filter", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    values = {
        "PLATFORM": args.platform,
        "CONFIGURATION": args.configuration,
        "TELEMETRY": args.telemetry,
        "FAST_FILTER": args.fast_filter,
        "BUILD_IDENTIFIER": hashlib.sha256(
            f"{args.platform}:{args.configuration}:{args.telemetry}:{args.fast_filter}".encode()
        ).hexdigest()[:12],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    _render(root / "templates/build_config.h.in", args.output / "build_config.h", values)
    _render(root / "templates/version_info.c.in", args.output / "version_info.c", values)
    return 0


def _render(source: Path, destination: Path, values: dict[str, str]) -> None:
    content = source.read_text(encoding="utf-8")
    for name, value in values.items():
        content = content.replace(f"@{name}@", value)
    destination.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
