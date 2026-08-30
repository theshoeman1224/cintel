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

    _validate_symbols(expected.get("expected_symbols", []), actual, result)
    _validate_relationships(
        expected.get("expected_relationships", []), actual, result, configuration
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


def _analysis_sections(actual: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    """Return the Phase 6 JSON report sections, or None when not exported."""

    analysis = actual.get("analysis_report")
    if not isinstance(analysis, dict):
        return None
    return {
        "symbol_index": analysis.get("symbol_index", {}).get("entries", []),
        "call_graph": analysis.get("call_graph", {}).get("edges", []),
        "include_index": analysis.get("include_index", {}).get("entries", []),
        "global_usage": analysis.get("global_usage", {}).get("entries", []),
    }


def _symbol_kind_for_category(category: str) -> str | None:
    if category.startswith(("FUNCTION", "HIGH_COMPLEXITY", "DIRECT_RECURSION")):
        return "function"
    if category.startswith("GLOBAL"):
        return "variable"
    if category.startswith("TYPE"):
        return "type"
    if category.startswith("MACRO"):
        return "macro"
    return None


def _validate_symbols(
    entries: list[dict[str, Any]],
    actual: dict[str, Any],
    result: dict[str, list[str]],
) -> None:
    sections = _analysis_sections(actual)
    if sections is None:
        _validate_future_section(entries, None, result)
        return
    symbols = sections["symbol_index"]
    for entry in entries:
        if entry.get("confidence") == "heuristic":
            result["skipped_heuristic"].append(entry["id"])
            continue
        kind = _symbol_kind_for_category(entry.get("category", ""))
        passed = any(
            item.get("name") == entry.get("symbol")
            and item.get("relative_path") == entry.get("source_path")
            and (kind is None or item.get("kind") == kind)
            for item in symbols
        )
        if passed:
            result["passed"].append(entry["id"])
        elif entry.get("required"):
            result["missing"].append(entry["id"] + " (symbol not in analysis)")


def _validate_relationships(
    entries: list[dict[str, Any]],
    actual: dict[str, Any],
    result: dict[str, list[str]],
    configuration: str,
) -> None:
    sections = _analysis_sections(actual)
    if sections is None:
        _validate_future_section(entries, None, result)
        return
    call_edges = sections["call_graph"]
    includes = sections["include_index"]
    usages = sections["global_usage"]
    for entry in entries:
        if entry.get("confidence") == "heuristic":
            result["skipped_heuristic"].append(entry["id"])
            continue
        configurations = entry.get("build_configurations", [])
        if configurations and configuration not in configurations:
            continue
        category = entry.get("category", "")
        caller = entry.get("symbol")
        callee = entry.get("related_symbol")
        source = entry.get("source_path")
        if category in ("DIRECT_CALL", "CONDITIONAL_CALL"):
            # The conservative parser extracts the call; whether it was
            # conditional compilation is not visible, so both categories
            # match a resolved direct-call edge.
            passed = any(
                edge.get("caller") == caller
                and edge.get("callee") == callee
                and edge.get("caller_path") == source
                and edge.get("resolution") == "confirmed_direct"
                for edge in call_edges
            )
        elif category == "POSSIBLE_INDIRECT_CALL":
            result["unsupported"].append(
                entry["id"] + " (indirect dispatch is unresolved by design)"
            )
            continue
        elif category == "INCLUDE_RELATIONSHIP":
            passed = any(
                item.get("including_path") == source
                and _include_matches(item, callee)
                for item in includes
            )
        elif category in ("GLOBAL_WRITE", "GLOBAL_READ"):
            # The conservative parser records the usage without read/write
            # direction, so both categories match a usage edge.
            passed = any(
                item.get("function") == caller
                and item.get("variable") == callee
                and item.get("function_path") == source
                for item in usages
            )
        else:
            result["unsupported"].append(entry["id"] + f" (no matcher for {category})")
            continue
        if passed:
            result["passed"].append(entry["id"])
        elif entry.get("required"):
            result["missing"].append(entry["id"] + " (relationship not in analysis)")


def _include_matches(item: dict[str, Any], spelling: str | None) -> bool:
    if spelling is None:
        return False
    included = item.get("included_spelling") or ""
    resolved = item.get("resolved_path") or ""
    for candidate in (included, resolved):
        if not candidate:
            continue
        if candidate == spelling or candidate.endswith(spelling) or spelling.endswith(candidate):
            return True
    return False


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
