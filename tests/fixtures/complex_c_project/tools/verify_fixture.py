#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "expected/expected_findings.json"
SAMPLES = ROOT / "expected/sample_inputs"

VALID_CATEGORIES = {
    "FUNCTION_DECLARATION", "FUNCTION_DEFINITION", "DIRECT_CALL", "CONDITIONAL_CALL",
    "POSSIBLE_INDIRECT_CALL", "DECLARATION_DEFINITION_LINK", "INCLUDE_RELATIONSHIP",
    "INCLUDE_CYCLE", "GLOBAL_DECLARATION", "GLOBAL_READ", "GLOBAL_WRITE",
    "VOLATILE_GLOBAL", "STATIC_SYMBOL", "DUPLICATE_STATIC_NAME", "TYPE_DEFINITION",
    "MACRO_DEFINITION", "MACRO_GENERATED_SYMBOL", "DIRECT_RECURSION", "HIGH_COMPLEXITY",
    "WEAK_SYMBOL", "GENERATED_FILE", "BUILD_EXCLUDED_FILE", "MULTI_CONFIGURATION_UNIT",
    "THIRD_PARTY_DEPENDENCY", "UNSUPPORTED_LANGUAGE_FILE",
}

REQUIRED_PATHS = (
    "Makefile", "mk/common.mk", "mk/features.mk", "mk/platform.mk", "mk/sources.mk",
    "mk/rules.mk", "include/cintel_fixture/application.h", "include/cintel_fixture/router.h",
    "src/app/main.c", "src/core/application.c", "src/routing/router.c",
    "src/shared/checksum.c", "src/plugins/Makefile", "src/legacy/unused_legacy_module.c",
    "generated/.gitkeep", "tools/compiler_wrapper.sh", "tools/generate_build_files.py",
    "expected/expected_findings.json", "unsupported/legacy_startup.S",
)


def main() -> int:
    failures: list[str] = []
    _verify_structure(failures)
    comments = _collect_expectations(failures)
    _verify_manifest(comments, failures)

    for executable in ("make", "gcc", "python3"):
        if shutil.which(executable) is None:
            failures.append(f"required build tool is unavailable: {executable}")
    if not failures:
        _run(["make", "clean"], failures)
        _run(["make", "generate", "CONFIG=linux"], failures)
        _require_generated(failures)
        _run(["make", "linux", "V=1"], failures)
        _run(["make", "embedded", "V=1"], failures)
        _run(["make", "tests", "V=1"], failures)
        _run(["make", "run-tests", "V=1"], failures)
        samples = _capture_samples(failures)
        _verify_samples(samples, failures)

    if failures:
        print("Fixture verification failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(
        f"Fixture verification passed: {len(comments)} expectation comments, "
        f"{len(list(SAMPLES.glob('*.txt')))} dry-run samples."
    )
    return 0


def _verify_structure(failures: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).exists():
            failures.append(f"required fixture path is missing: {relative}")
    source_directories = {path.parent.relative_to(ROOT) for path in ROOT.glob("src/**/*.c")}
    if len(source_directories) < 8:
        failures.append(f"expected at least 8 source directories, found {len(source_directories)}")


def _collect_expectations(failures: list[str]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    pattern = re.compile(r"CINTEL_EXPECT\[([A-Z_]+)\]")
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".c", ".h", ".S", ".in"} or "build" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for category in pattern.findall(text):
            relative = path.relative_to(ROOT).as_posix()
            findings.append((relative, category))
            if category not in VALID_CATEGORIES:
                failures.append(f"unknown expectation category {category} in {relative}")
    missing_categories = VALID_CATEGORIES - {category for _, category in findings}
    if missing_categories:
        failures.append("missing expectation categories: " + ", ".join(sorted(missing_categories)))
    return findings


def _verify_manifest(comments: list[tuple[str, str]], failures: list[str]) -> None:
    try:
        manifest = json.loads(EXPECTED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"cannot read expectation manifest: {error}")
        return
    if manifest.get("schema_version") != 1:
        failures.append("expectation manifest schema_version must be 1")
    comment_set = set(comments)
    ids: set[str] = set()
    for section in (
        "expected_files", "expected_symbols", "expected_relationships",
        "expected_build_properties", "expected_diagnostics",
    ):
        for entry in manifest.get(section, []):
            entry_id = entry.get("id")
            if not entry_id or entry_id in ids:
                failures.append(f"missing or duplicate manifest id: {entry_id!r}")
            ids.add(entry_id)
            if not entry.get("required"):
                continue
            source = entry.get("source_path")
            category = entry.get("category")
            if section == "expected_files" and source and (ROOT / source).exists():
                continue
            if category == "GENERATED_FILE" and source:
                template = f"templates/{Path(source).name}.in"
                if (template, category) in comment_set:
                    continue
            if entry.get("rationale"):
                continue
            if source and (source, category) in comment_set:
                continue
            failures.append(
                f"required manifest entry {entry_id} lacks a matching expectation comment or rationale"
            )


def _run(arguments: list[str], failures: list[str]) -> str:
    completed = subprocess.run(
        arguments, cwd=ROOT, text=True, capture_output=True, check=False, timeout=120
    )
    if completed.returncode != 0:
        failures.append(
            f"command failed ({' '.join(arguments)}): "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout + completed.stderr


def _require_generated(failures: list[str]) -> None:
    for relative in ("generated/build_config.h", "generated/version_info.c"):
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"generator did not create valid {relative}")


def _capture_samples(failures: list[str]) -> dict[str, str]:
    commands = {
        "make-linux-dry-run.txt": ["make", "-n", "-B", "linux", "V=1"],
        "make-embedded-dry-run.txt": ["make", "-n", "-B", "embedded", "V=1"],
        "make-tests-dry-run.txt": ["make", "-n", "-B", "tests", "V=1"],
        "make-linux-wrapper-dry-run.txt": [
            "make", "-n", "-B", "linux", "V=1", "USE_COMPILER_WRAPPER=1"
        ],
        "make-missing-input-dry-run.txt": [
            "make", "-n", "-B", "missing-input-demo", "V=1"
        ],
    }
    SAMPLES.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for filename, command in commands.items():
        output = _run(command, failures)
        portable = output.replace(str(ROOT), "<FIXTURE_ROOT>")
        (SAMPLES / filename).write_text(portable, encoding="utf-8")
        outputs[filename] = portable
    return outputs


def _verify_samples(samples: dict[str, str], failures: list[str]) -> None:
    linux = samples.get("make-linux-dry-run.txt", "")
    embedded = samples.get("make-embedded-dry-run.txt", "")
    tests = samples.get("make-tests-dry-run.txt", "")
    wrapper = samples.get("make-linux-wrapper-dry-run.txt", "")
    missing = samples.get("make-missing-input-dry-run.txt", "")
    checks = (
        ("-DPLATFORM_LINUX" in linux and "-O2" in linux, "Linux dry-run lacks expected flags"),
        ("-DPLATFORM_EMBEDDED" in embedded and "-O0" in embedded, "embedded dry-run lacks expected flags"),
        ("-DUNIT_TEST" in tests, "test dry-run lacks UNIT_TEST"),
        ("src/shared/checksum.c" in linux and "src/shared/checksum.c" in embedded,
         "checksum.c is not compiled in both configurations"),
        ("Entering directory" in linux and "src/plugins" in linux,
         "recursive plugin Make activity is absent"),
        ("compiler_wrapper.sh" in wrapper, "wrapper dry-run lacks compiler wrapper"),
        ("unused_legacy_module.c" not in linux + embedded + tests,
         "unused legacy source appears in a selected build"),
        ("generated/build_config.h" in linux and "generated/version_info.c" in linux,
         "generated files are absent from Linux commands"),
        ("external_site_config.h" in missing,
         "missing-input dry-run lacks the intentionally absent input"),
        ("legacy_startup.S" not in linux + embedded + tests,
         "unsupported assembly appears in normal builds"),
        (" cc " in f" {linux} " or " gcc " in f" {linux} ",
         "Linux dry-run contains no compiler invocation"),
    )
    for passed, message in checks:
        if not passed:
            failures.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
