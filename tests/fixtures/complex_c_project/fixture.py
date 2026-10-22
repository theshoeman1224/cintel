"""Driver hooks for the complex C fixture.

All heavy lifting is delegated to the fixture's own tooling
(tools/verify_fixture.py, tools/validate_cintel_results.py) and the
documented cintel CLI flow; nothing here reimplements fixture logic and
no committed fixture file is modified.
"""

from __future__ import annotations

import json
import shutil
import sys

NAME = "complex_c_project"
DESCRIPTION = (
    "Self-building legacy C project exercising inventory, Make discovery, "
    "compiler flags, source intelligence, diagnostics, and graceful degradation."
)
REQUIRES = ("make", "gcc", "python3")

CONFIGURATION = "linux"
VERIFY_TIMEOUT = 600

# Report families the validator reads as `analysis_report`.
ANALYSIS_REPORTS = ("symbol_index", "call_graph", "include_index", "global_usage")
# The validator's label for a finding whose report family was not supplied.
NOT_EXPORTED = "not exported by current cintel phase"


def _tools(context):
    return context.fixture_root / "tools"


def setup(context) -> None:
    """Generate the gitignored artifacts cintel needs (build/, generated/)."""
    make = shutil.which("make")
    if make is None:
        raise RuntimeError("GNU Make is required to prepare the complex fixture")
    context.run([make, "clean"], timeout=120)
    context.run([make, "generate", "CONFIG=" + CONFIGURATION], timeout=120)
    print("  setup: generated outputs rebuilt (make clean; make generate)")


def verify(context) -> None:
    """Run the fixture's full self-verification (builds all configurations)."""
    script = _tools(context) / "verify_fixture.py"
    completed = context.run(
        [sys.executable, str(script)], timeout=VERIFY_TIMEOUT, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stdout + completed.stderr).strip())
    print("  verify: " + completed.stdout.strip())


def clean(context) -> None:
    """Remove build and generated outputs (gitignored artifacts only)."""
    make = shutil.which("make")
    if make is not None:
        context.run([make, "clean"], timeout=120, check=False)
    else:
        for relative in ("build", "generated/build_config.h", "generated/version_info.c"):
            target = context.fixture_root / relative
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                target.unlink(missing_ok=True)
    print("  clean: removed build and generated outputs")


def run(context) -> None:
    """End-to-end user flow: init, doctor, scan, build discover, analyze,
    report, then validate every finding against the expected manifest."""
    output_dir = context.output_dir or (
        context.repo_root / ".fixture-output" / NAME
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    with context.copy_to_tempdir() as workspace:
        common = [
            "--repository", str(workspace),
            "--output-directory", str(output_dir),
        ]
        build_common = [
            *common,
            "--makefile", "Makefile",
            "--target", CONFIGURATION,
            "--build-config", CONFIGURATION,
            "--non-interactive",
        ]

        print("  run: init")
        context.cintel(["init", str(workspace)])
        print("  run: doctor")
        doctor = context.cintel([*common, "doctor"], check=False)
        if doctor.returncode not in (0, 2):
            raise RuntimeError((doctor.stdout + doctor.stderr).strip())

        print("  run: generate fixture artifacts in workspace")
        context.run(["make", "generate", "CONFIG=" + CONFIGURATION], cwd=workspace)

        print("  run: scan")
        scan = context.cintel([*common, "scan"])
        print("  " + "\n  ".join(scan.stdout.strip().splitlines()[-3:]))

        print("  run: build discover (live make dry-run)")
        discover = context.cintel([*build_common, "--force-build-discovery", "--json", "build", "discover"])
        build_report = json.loads(discover.stdout)

        print("  run: analyze")
        context.cintel([*common, "--build-config", CONFIGURATION, "analyze"])

        print("  run: report")
        context.cintel([*common, "report"])

        print("  run: validate against expected findings")

        def load_report(name):
            path = output_dir / "reports" / f"{name}.json"
            return json.loads(path.read_text(encoding="utf-8"))

        actual = output_dir / "actual.json"
        actual.write_text(
            json.dumps(
                {
                    "repository_report": load_report("repository"),
                    "build_report": build_report,
                    "analysis_report": {
                        name: load_report(name) for name in ANALYSIS_REPORTS
                    },
                }
            ),
            encoding="utf-8",
        )
        validation = context.run(
            [
                sys.executable,
                str(_tools(context) / "validate_cintel_results.py"),
                "--expected", str(context.fixture_root / "expected" / "expected_findings.json"),
                "--actual", str(actual),
                "--configuration", CONFIGURATION,
            ],
            cwd=context.repo_root,
            check=False,
        )
        print("  " + "\n  ".join(validation.stdout.strip().splitlines()))
        if validation.returncode != 0:
            raise RuntimeError("expected-findings validation reported missing or conflicting results")
        if "Missing: 0" not in validation.stdout:
            raise RuntimeError("expected-findings validation did not pass cleanly")
        if NOT_EXPORTED in validation.stdout:
            raise RuntimeError(
                "analysis findings were not validated; the analysis reports "
                "are missing from the validation envelope"
            )

    print(f"  run: outputs in {output_dir}")
