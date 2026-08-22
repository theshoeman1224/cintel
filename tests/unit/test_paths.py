import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cintel.utilities.paths import (
    is_excluded,
    stable_repository_id,
)


class StableRepositoryIdTests(unittest.TestCase):
    def test_matches_across_trailing_separator_and_dot_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            repository.mkdir()
            previous = Path.cwd()
            os.chdir(root)
            self.addCleanup(os.chdir, previous)

            spellings = (
                str(repository),
                str(repository) + "/",
                "./repo",
                "repo",
            )
            identifiers = {stable_repository_id(spelling) for spelling in spellings}
            self.assertEqual(1, len(identifiers))

    def test_matches_through_a_symlinked_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            repository.mkdir()
            link = root / "link"
            link.symlink_to(repository, target_is_directory=True)

            self.assertEqual(
                stable_repository_id(repository), stable_repository_id(link)
            )

    def test_expands_home_relative_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            repository.mkdir()
            with mock.patch.dict(os.environ, {"HOME": str(root)}):
                from_home = stable_repository_id("~/repo")
            direct = stable_repository_id(repository)

            self.assertEqual(direct, from_home)


class ExclusionMatcherTests(unittest.TestCase):
    def test_matches_name_value_and_path_parts(self) -> None:
        patterns = ("build", "*.log", "third_party/generated/*")
        self.assertTrue(is_excluded(Path("build/main.c"), patterns))
        self.assertTrue(is_excluded(Path("src/build"), patterns))
        self.assertTrue(is_excluded(Path("src/debug.log"), patterns))
        self.assertTrue(is_excluded(Path("third_party/generated/stub.c"), patterns))

    def test_keeps_unrelated_paths(self) -> None:
        patterns = ("build", "*.log")
        self.assertFalse(is_excluded(Path("src/main.c"), patterns))
        self.assertFalse(is_excluded(Path("builder/main.c"), patterns))


if __name__ == "__main__":
    unittest.main()
