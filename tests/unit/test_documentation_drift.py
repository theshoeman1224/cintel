"""Drift guards: user-facing docs keep up with what the code exposes.

Cheap structural checks that fail when a report family, CLI flag or
command, diagnostic family, or doc file is added without its documentation.
"""

import argparse
import re
import unittest
from pathlib import Path

from cintel.application.reports import _REPORT_FAMILIES
from cintel.cli.main import build_parser
from cintel.domain.diagnostics import DiagnosticCode

PROJECT_ROOT = Path(__file__).parents[2]
README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def _cli_surface(parser: argparse.ArgumentParser, prefix: str = ""):
    """Yield ("flag", "--name") and ("command", "build units") pairs."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                command = f"{prefix} {name}".strip()
                yield "command", command
                yield from _cli_surface(subparser, command)
            continue
        for option in action.option_strings:
            if option.startswith("--") and option != "--help":
                yield "flag", option


class DocumentationDriftTests(unittest.TestCase):
    def test_readme_lists_every_report_family(self) -> None:
        reports = README.split("\n## Reports\n", 1)[1].split("\n## ", 1)[0]
        documented = set(re.findall(r"reports/(\w+)\.\{md,json\}", reports))
        self.assertEqual(set(_REPORT_FAMILIES), documented)

    def test_readme_mentions_every_cli_flag_and_command(self) -> None:
        missing = sorted(
            value
            for kind, value in set(_cli_surface(build_parser()))
            if (value if kind == "flag" else f"`{value}") not in README
        )
        self.assertEqual([], missing)

    def test_roadmap_lists_every_diagnostic_family(self) -> None:
        roadmap = (
            PROJECT_ROOT / "docs" / "CURRENT_CAPABILITIES_AND_MVP_ROADMAP.md"
        ).read_text(encoding="utf-8")
        families = {code.value.rsplit("-", 1)[0] for code in DiagnosticCode}
        missing = sorted(family for family in families if f"`{family}-" not in roadmap)
        self.assertEqual([], missing)

    def test_agents_doc_map_lists_every_doc(self) -> None:
        agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        doc_map = agents.split("\n## Docs\n", 1)[1]
        missing = sorted(
            path.name
            for path in (PROJECT_ROOT / "docs").glob("*.md")
            if f"`docs/{path.name}`" not in doc_map
        )
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
