import json
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.reports import JSONReportRenderer, MarkdownReportRenderer
from cintel.adapters.repositories import FileSystemRepositoryDiscovery


class RepositoryReportTests(unittest.TestCase):
    def test_markdown_and_json_distinguish_evidence_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
            scan = FileSystemRepositoryDiscovery().discover(
                str(root), "repository-1", ()
            )

            markdown = MarkdownReportRenderer().render("repository_inventory", scan)
            json_text = JSONReportRenderer().render("repository_inventory", scan)
            payload = json.loads(json_text)

            self.assertIn("extracted fact", markdown)
            self.assertIn("calculated metric", markdown)
            self.assertIn("unavailable information", markdown)
            self.assertEqual("calculated_metric", payload["metrics"]["classification"])
            self.assertEqual("extracted_fact", payload["files"][0]["classification"])

