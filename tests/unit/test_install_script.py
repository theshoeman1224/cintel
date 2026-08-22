from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install.py"
SCRIPT_SPEC = spec_from_file_location("cintel_install_script", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
INSTALL_SCRIPT = module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(INSTALL_SCRIPT)


class InstallScriptTests(unittest.TestCase):
    def test_skips_install_when_project_version_is_installed(self) -> None:
        distribution_name, project_version = INSTALL_SCRIPT.project_metadata()
        with (
            patch.object(INSTALL_SCRIPT, "installed_version", return_value=project_version),
            patch.object(INSTALL_SCRIPT.subprocess, "run") as run,
            patch("builtins.print") as print_message,
        ):
            result = INSTALL_SCRIPT.main()

        self.assertEqual(result, 0)
        run.assert_not_called()
        print_message.assert_called_once_with(
            f"{distribution_name} {project_version} is already installed; "
            "skipping installation."
        )

    def test_installs_editable_project_when_version_differs(self) -> None:
        completed = SimpleNamespace(returncode=3)
        with (
            patch.object(INSTALL_SCRIPT, "installed_version", return_value="0.0.9"),
            patch.object(INSTALL_SCRIPT.subprocess, "run", return_value=completed) as run,
        ):
            result = INSTALL_SCRIPT.main()

        self.assertEqual(result, 3)
        run.assert_called_once_with(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-e",
                str(INSTALL_SCRIPT.PROJECT_ROOT),
            ],
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
