import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cintel.cli.main import main


def _copy_fixture(destination: Path) -> Path:
    fixture = Path(__file__).parents[1] / "fixtures" / "repositories" / "basic"
    shutil.copytree(fixture, destination)
    return destination


class QueryCommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.workspace = _copy_fixture(Path(self._temporary.name) / "repo")
        self._run("init", str(self.workspace))
        self._run("--repository", str(self.workspace), "scan")
        self._run("--repository", str(self.workspace), "analyze")

    def _run(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(arguments))
        return code, output.getvalue()

    def test_symbols_lists_analyzed_functions(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace), "--json", "symbols",
            "--kind", "function",
        )
        self.assertEqual(0, code)
        payload = json.loads(text)
        names = {entry["name"] for entry in payload["entries"]}
        self.assertEqual(
            {"project_value", "main", "not_in_the_selected_build"}, names
        )

        code, text = self._run(
            "--repository", str(self.workspace), "symbols", "project_value"
        )
        self.assertEqual(0, code)
        self.assertIn("src/main.c", text)
        self.assertIn("include/project.h", text)

    def test_show_function_reports_definition_callers_and_declarations(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace), "show", "function", "project_value"
        )
        self.assertEqual(0, code)
        self.assertIn("src/main.c:3", text)
        self.assertIn("Callers: 1", text)
        self.assertIn("main", text)
        self.assertIn("Declarations:", text)

        code, text = self._run(
            "--repository", str(self.workspace), "--json", "show", "function",
            "project_value",
        )
        self.assertEqual(0, code)
        payload = json.loads(text)
        self.assertEqual("project_value", payload["definition"]["name"])
        self.assertEqual("main", payload["callers"][0]["function_name"])

    def test_callers_and_callees_report_resolved_edges(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace), "callers", "project_value"
        )
        self.assertEqual(0, code)
        self.assertIn("main", text)

        code, text = self._run(
            "--repository", str(self.workspace), "callees", "main"
        )
        self.assertEqual(0, code)
        self.assertIn("project_value", text)

        code, text = self._run(
            "--repository", str(self.workspace), "--json", "callees", "main"
        )
        self.assertEqual(0, code)
        payload = json.loads(text)
        self.assertEqual("confirmed_direct", payload[0]["resolution"])

    def test_empty_results_exit_with_no_match(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace), "callees", "project_value"
        )
        self.assertEqual(1, code)
        self.assertIn("No call relationships", text)

        code, text = self._run(
            "--repository", str(self.workspace), "show", "function", "absent"
        )
        self.assertEqual(1, code)

        code, _ = self._run(
            "--repository", str(self.workspace), "symbols", "absent"
        )
        self.assertEqual(1, code)

    def test_duplicate_definitions_require_file_disambiguation(self) -> None:
        (self.workspace / "duplicate.c").write_text(
            "int project_value(void) {\n    return 5;\n}\n", encoding="utf-8"
        )
        self._run("--repository", str(self.workspace), "scan")
        self._run("--repository", str(self.workspace), "analyze")

        code, text = self._run(
            "--repository", str(self.workspace), "show", "function", "project_value"
        )
        self.assertEqual(1, code)
        self.assertIn("Ambiguous function name", text)
        self.assertIn("duplicate.c:1", text)
        self.assertIn("--file", text)

        code, text = self._run(
            "--repository", str(self.workspace), "show", "function",
            "project_value", "--file", "duplicate.c",
        )
        self.assertEqual(0, code)
        self.assertIn("duplicate.c:1", text)

        code, text = self._run(
            "--repository", str(self.workspace), "callers", "project_value"
        )
        self.assertEqual(1, code)

        code, text = self._run(
            "--repository", str(self.workspace), "callers", "project_value",
            "--file", "duplicate.c",
        )
        # Phase 5B resolution is monotonic: main.c's already-resolved call
        # keeps pointing at its original target, so the duplicate definition
        # legitimately has no callers.
        self.assertEqual(1, code)
        self.assertIn("No call relationships", text)

    def test_context_function_writes_package_under_context_directory(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace),
            "context", "function", "project_value",
        )
        self.assertEqual(0, code)
        self.assertIn("context/project_value__src_main_c.md", text)
        self.assertIn("Budget:", text)

        package_path = (
            self.workspace / ".code-intelligence" / "context"
            / "project_value__src_main_c.md"
        )
        self.assertTrue(package_path.is_file())
        content = package_path.read_text(encoding="utf-8")
        self.assertIn("# Context for project_value", content)
        self.assertIn("## Definition", content)
        self.assertIn("## Callers", content)
        self.assertIn("```c", content)

        code, text = self._run(
            "--repository", str(self.workspace), "--json",
            "context", "function", "project_value",
        )
        self.assertEqual(0, code)
        payload = json.loads(text)
        self.assertTrue(payload["package"]["function_id"].startswith("function-"))
        self.assertLessEqual(
            payload["package"]["used_characters"],
            payload["package"]["character_budget"],
        )

        code, text = self._run(
            "--repository", str(self.workspace),
            "context", "function", "project_value", "--budget", "150",
        )
        self.assertEqual(0, code)
        self.assertIn("[degraded]", text)
        self.assertIn("exceeded the 150 character budget", text)

    def test_context_function_ambiguous_name_exits_no_match(self) -> None:
        code, text = self._run(
            "--repository", str(self.workspace),
            "context", "function", "absent_function",
        )
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
