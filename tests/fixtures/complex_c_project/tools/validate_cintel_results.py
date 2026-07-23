#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--configuration", required=True)
    args = parser.parse_args(argv)

    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    actual = json.loads(args.actual.read_text(encoding="utf-8"))
    result = validate(expected, actual, args.configuration)
    for label in ("passed", "missing", "conflicts", "skipped_heuristic", "unsupported"):
        print(f"{label.replace('_', ' ').title()}: {len(result[label])}")
        for entry in result[label]:
            print(f"  - {entry}")
    print(
        "Summary: "
        + ", ".join(f"{name}={len(values)}" for name, values in result.items())
    )
    return 1 if result["missing"] or result["conflicts"] else 0


def validate(expected: dict[str, Any], actual: dict[str, Any], configuration: str) -> dict[str, list[str]]:
    result = {name: [] for name in ("passed", "missing", "conflicts", "skipped_heuristic", "unsupported")}
    repository = actual.get("repository_report", actual if actual.get("report") == "repository_inventory" else {})
    build = actual.get("build_report", actual if "compilation_units" in actual else {})
    root = Path(repository.get("repository", {}).get("root", "/"))
    files = {item.get("relative_path") for item in repository.get("files", [])}
    units = build.get("compilation_units", [])
    unit_sources = {
        item.get("compiler_invocation", {}).get("source", {}).get("repository_relative")
        for item in units
    }
    excluded = {_relative(path, root) for path in build.get("excluded_source_files", [])}
    defines = {
        _define_text(item)
        for unit in units
        for item in unit.get("compiler_invocation", {}).get("arguments", {}).get("defines", [])
    }
    include_paths = {
        item.get("path", {}).get("repository_relative") or item.get("path", {}).get("original")
        for unit in units
        for item in unit.get("compiler_invocation", {}).get("arguments", {}).get("include_paths", [])
    }
    forced_includes = {
        item.get("repository_relative") or item.get("original")
        for unit in units
        for item in unit.get("compiler_invocation", {}).get("arguments", {}).get("forced_includes", [])
    }

    for entry in expected.get("expected_files", []):
        if entry.get("confidence") == "heuristic":
            result["skipped_heuristic"].append(entry["id"])
        elif entry.get("category") == "UNSUPPORTED_LANGUAGE_FILE":
            result["unsupported"].append(entry["id"] + " (C-only inventory)")
        elif entry.get("source_path") in files:
            result["passed"].append(entry["id"])
        elif entry.get("required"):
            result["missing"].append(entry["id"])

    for entry in expected.get("expected_build_properties", []):
        configurations = entry.get("build_configurations", [])
        if configurations and configuration not in configurations:
            continue
        category = entry.get("category")
        value = entry.get("value")
        source = entry.get("source_path")
        passed = False
        if category == "DEFINE":
            passed = value in defines
        elif category == "INCLUDE_PATH":
            passed = any(path and path.endswith(value) for path in include_paths)
        elif category == "FORCED_INCLUDE":
            passed = any(path and path.endswith(value) for path in forced_includes)
        elif category in {"MULTI_CONFIGURATION_UNIT", "BUILD_MEMBERSHIP"}:
            passed = source in unit_sources
        elif category == "BUILD_EXCLUSION":
            passed = source in excluded
        if passed:
            result["passed"].append(entry["id"])
        elif entry.get("required"):
            result["missing"].append(entry["id"])

    _validate_future_section(expected.get("expected_symbols", []), actual.get("symbols"), result)
    _validate_future_section(
        expected.get("expected_relationships", []), actual.get("relationships"), result
    )

    for entry in expected.get("expected_diagnostics", []):
        configurations = entry.get("build_configurations", [])
        if configurations and configuration not in configurations:
            continue
        diagnostics = repository.get("diagnostics", []) + build.get("diagnostics", [])
        if not diagnostics:
            result["unsupported"].append(entry["id"] + " (diagnostic not exported for this target)")
        else:
            result["unsupported"].append(entry["id"] + " (diagnostic matcher pending target run)")
    return result


def _validate_future_section(entries: list[dict[str, Any]], actual: Any, result: dict[str, list[str]]) -> None:
    if actual is None:
        for entry in entries:
            bucket = "skipped_heuristic" if entry.get("confidence") == "heuristic" else "unsupported"
            result[bucket].append(entry["id"] + " (not exported by current cintel phase)")
        return
    actual_ids = {item.get("id") for item in actual}
    for entry in entries:
        if entry["id"] in actual_ids:
            result["passed"].append(entry["id"])
        elif entry.get("confidence") == "heuristic":
            result["skipped_heuristic"].append(entry["id"])
        elif entry.get("required"):
            result["missing"].append(entry["id"])


def _define_text(item: dict[str, Any]) -> str:
    return item.get("name", "") + (f"={item['value']}" if item.get("value") is not None else "")


def _relative(value: str, root: Path) -> str:
    try:
        return Path(value).resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return value


if __name__ == "__main__":
    raise SystemExit(main())
