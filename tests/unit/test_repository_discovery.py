import os
import tempfile
import unittest
from pathlib import Path

from cintel.adapters.repositories import FileSystemRepositoryDiscovery
from cintel.configuration.models import DEFAULT_EXCLUSIONS
from cintel.domain.models import FileKind


class RepositoryDiscoveryTests(unittest.TestCase):
    def test_discovers_relevant_files_and_applies_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.c").write_text("int main(void){}\n", encoding="utf-8")
            (root / "src" / "main.h").write_text("#pragma once\n", encoding="utf-8")
            (root / "Makefile").write_text("all:\n", encoding="utf-8")
            (root / "rules.mk").write_text("CC=gcc\n", encoding="utf-8")
            (root / "notes.txt").write_text("ignore\n", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "generated.c").write_text("int x;\n", encoding="utf-8")

            result = FileSystemRepositoryDiscovery().discover(
                str(root), "repository-1", DEFAULT_EXCLUSIONS
            )

            self.assertEqual(
                ("Makefile", "rules.mk", "src/main.c", "src/main.h"),
                tuple(item.relative_path for item in result.files),
            )
            self.assertEqual(
                {
                    FileKind.C_SOURCE,
                    FileKind.C_HEADER,
                    FileKind.MAKEFILE,
                    FileKind.MAKE_FRAGMENT,
                },
                {item.kind for item in result.files},
            )
            self.assertEqual(4, result.hashes_computed)
            self.assertEqual(0, result.hashes_reused)

    def test_reuses_unchanged_hashes_and_rehashes_changed_file(self) -> None:
        calls: list[Path] = []

        def hashing(path: Path) -> str:
            calls.append(path)
            return f"hash-{len(calls)}"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.c"
            source.write_text("int one;\n", encoding="utf-8")
            discovery = FileSystemRepositoryDiscovery(hashing)
            first = discovery.discover(str(root), "repository-1", ())
            second = discovery.discover(
                str(root), "repository-1", (), first.files
            )
            source.write_text("int two;\n", encoding="utf-8")
            stat = source.stat()
            os.utime(source, (stat.st_atime, stat.st_mtime + 2))
            third = discovery.discover(
                str(root), "repository-1", (), second.files
            )

            self.assertEqual(1, first.hashes_computed)
            self.assertEqual(1, second.hashes_reused)
            self.assertEqual(0, second.hashes_computed)
            self.assertEqual(1, third.hashes_computed)
            self.assertEqual(2, len(calls))

    def test_missing_repository_degrades_with_structured_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            result = FileSystemRepositoryDiscovery().discover(
                str(missing), "repository-1", ()
            )
            self.assertEqual((), result.files)
            self.assertEqual("CI-REPO-001", result.diagnostics[0].code)

    def test_hash_failure_is_reported_and_other_files_continue(self) -> None:
        def hashing(path: Path) -> str:
            if path.name == "broken.c":
                raise OSError("simulated read failure")
            return "a" * 64

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.c").write_text("int broken;\n", encoding="utf-8")
            (root / "usable.h").write_text("#pragma once\n", encoding="utf-8")

            result = FileSystemRepositoryDiscovery(hashing).discover(
                str(root), "repository-1", ()
            )

            self.assertEqual(("usable.h",), tuple(item.relative_path for item in result.files))
            self.assertIn("CI-REPO-004", {item.code for item in result.diagnostics})
            self.assertEqual("degraded", result.capabilities[0].status.value)

    def test_skips_source_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.c"
            target.write_text("int real;\n", encoding="utf-8")
            link = root / "linked.c"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symbolic links are unavailable")

            result = FileSystemRepositoryDiscovery().discover(
                str(root), "repository-1", ()
            )
            self.assertEqual(("real.c",), tuple(item.relative_path for item in result.files))
            self.assertIn("CI-REPO-003", {item.code for item in result.diagnostics})
