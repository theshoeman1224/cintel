"""Driver hooks for the minimal basic repository fixture."""

from __future__ import annotations

import json
import shutil

DESCRIPTION = "Minimal Make-based C repository used by CLI and analysis integration tests."

EXPECTED_FILES = (
    "Makefile",
    "src/main.c",
    "include/project.h",
    "orphan.c",
)


def setup(context) -> None:
    print("  setup: nothing to do (source-only fixture)")


def verify(context) -> None:
    missing = [
        relative
        for relative in EXPECTED_FILES
        if not (context.fixture_root / relative).is_file()
    ]
    if missing:
        raise RuntimeError("required fixture files are missing: " + ", ".join(missing))
    stray = context.fixture_root / ".code-intelligence"
    if stray.exists():
        raise RuntimeError(f"stray generated state present (run 'clean'): {stray}")
    print(f"  verify: {len(EXPECTED_FILES)} expected files present, no stray state")


def clean(context) -> None:
    stray = context.fixture_root / ".code-intelligence"
    if stray.exists():
        shutil.rmtree(stray)
        print("  clean: removed stray .code-intelligence")
    else:
        print("  clean: nothing to clean")


def run(context) -> None:
    """End-to-end user flow on a disposable copy: init, scan, check results."""
    with context.copy_to_tempdir() as workspace:
        print("  run: init")
        context.cintel(["init", str(workspace)])

        print("  run: scan")
        scan = context.cintel(["--repository", str(workspace), "scan"])
        print("  " + "\n  ".join(scan.stdout.strip().splitlines()[-3:]))
        if "Relevant files: 4" not in scan.stdout:
            raise RuntimeError("scan did not report the expected 4 relevant files")

        report_path = workspace / ".code-intelligence" / "reports" / "repository.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        recorded = report["metrics"]["files_recorded"]
        if recorded != 4:
            raise RuntimeError(f"repository report recorded {recorded} files, expected 4")

        print("  run: incremental scan reuses results")
        second = context.cintel(["--repository", str(workspace), "scan"])
        if "0 computed, 4 reused" not in second.stdout:
            raise RuntimeError("incremental scan did not reuse the previous results")
