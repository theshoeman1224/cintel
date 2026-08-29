import tempfile
import unittest
from pathlib import Path

from cintel.utilities.hashing import sha256_file, stable_fingerprint, stable_id


class HashingTests(unittest.TestCase):
    def test_file_hash_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.c"
            path.write_bytes(b"int main(void) { return 0; }\n")
            self.assertEqual(
                "2ad75d95660563887d8d3f1d0ae1dcf18c2379cbd83a5c72f5ab276351ee6949",
                sha256_file(path),
            )

    def test_ids_and_fingerprints_ignore_mapping_order(self) -> None:
        self.assertEqual(
            "file-3953e30b1441063e6a03b4fa",
            stable_id("file", "a.c"),
        )
        self.assertEqual(
            stable_fingerprint({"target": "all", "vars": {"B": 2, "A": 1}}),
            stable_fingerprint({"vars": {"A": 1, "B": 2}, "target": "all"}),
        )
