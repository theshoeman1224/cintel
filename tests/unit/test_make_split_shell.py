import unittest

from cintel.adapters.build.make import _split_shell_commands


class SplitShellCommandsSnapshotTests(unittest.TestCase):
    """Snapshot tests pinning exact splitting behavior before refactoring."""

    def test_splits_on_semicolons(self) -> None:
        self.assertEqual(("a", "b", "c"), _split_shell_commands("a;b;c"))

    def test_splits_on_unquoted_and_and(self) -> None:
        self.assertEqual(("a ", " b"), _split_shell_commands("a && b"))

    def test_keeps_semicolons_inside_double_quotes(self) -> None:
        self.assertEqual(('echo "a;b"',), _split_shell_commands('echo "a;b"'))

    def test_keeps_semicolons_inside_single_quotes(self) -> None:
        self.assertEqual(("echo 'a;b'",), _split_shell_commands("echo 'a;b'"))

    def test_escaped_semicolon_is_content(self) -> None:
        self.assertEqual(("echo a\\;b",), _split_shell_commands("echo a\\;b"))

    def test_escaped_backslash_then_separator(self) -> None:
        self.assertEqual(("echo a\\\\", "b"), _split_shell_commands("echo a\\\\;b"))

    def test_double_quoted_apostrophe_does_not_open_single_quote(self) -> None:
        self.assertEqual(('echo "it\'s"', "b"), _split_shell_commands("echo \"it's\";b"))

    def test_single_quote_backslash_is_not_an_escape(self) -> None:
        self.assertEqual(("echo 'a\\'", "b'"), _split_shell_commands("echo 'a\\';b'"))

    def test_mixed_separators(self) -> None:
        self.assertEqual(
            ("cmd1 ", " cmd2 ", " cmd3 ", " cmd4"),
            _split_shell_commands("cmd1 ; cmd2 && cmd3 ; cmd4"),
        )

    def test_and_and_inside_double_quotes_is_content(self) -> None:
        self.assertEqual(
            ('gcc -DSTR="x && y" -c a.c',),
            _split_shell_commands('gcc -DSTR="x && y" -c a.c'),
        )

    def test_trailing_backslash_is_content(self) -> None:
        self.assertEqual(("backslash end\\",), _split_shell_commands("backslash end\\"))

    def test_single_ampersand_is_content(self) -> None:
        self.assertEqual(("a&b",), _split_shell_commands("a&b"))

    def test_triple_ampersand_splits_on_first_pair(self) -> None:
        self.assertEqual(("a ", "& b"), _split_shell_commands("a &&& b"))

    def test_mixed_quoting(self) -> None:
        self.assertEqual(
            ('mix "q1;q2" ', " 's1;s2' ", " tail"),
            _split_shell_commands("mix \"q1;q2\" && 's1;s2' ; tail"),
        )


if __name__ == "__main__":
    unittest.main()
