from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
import subprocess
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = PROJECT_ROOT / "pyproject.toml"


def project_metadata() -> tuple[str, str]:
    with PROJECT_FILE.open("rb") as project_file:
        project = tomllib.load(project_file)["project"]
    return project["name"], project["version"]


def installed_version(distribution_name: str) -> str | None:
    try:
        return distribution_version(distribution_name)
    except PackageNotFoundError:
        return None


def main() -> int:
    distribution_name, expected_version = project_metadata()
    current_version = installed_version(distribution_name)

    if current_version == expected_version:
        print(
            f"{distribution_name} {expected_version} is already installed; "
            "skipping installation."
        )
        return 0

    command = [sys.executable, "-m", "pip", "install", "-e", str(PROJECT_ROOT)]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
