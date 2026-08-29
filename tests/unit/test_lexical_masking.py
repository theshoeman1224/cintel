import unittest

from cintel.adapters.parsing import mask_c_non_code


class MaskCNonCodeSnapshotTests(unittest.TestCase):
    """Snapshot tests pinning exact masked output before refactoring.

    Masking errors are length-preserving, so they cannot trip the structural
    assertion inside mask_c_non_code. These exact-output cases are the safety
    net for the state machine.
    """

    def _assert_snapshot(
        self,
        source: str,
        expected_text: str,
        expected_issues: list[tuple[str, int, int]],
    ) -> None:
        result = mask_c_non_code(source)
        self.assertEqual(expected_text, result.text)
        self.assertEqual(
            expected_issues,
            [(issue.message, issue.offset, issue.end_offset) for issue in result.issues],
        )
        self.assertEqual(len(source), len(result.text))
        self.assertEqual(source.count("\n"), result.text.count("\n"))

    def test_line_comment_is_masked_to_newline(self) -> None:
        self._assert_snapshot(
            "int a; // hide me\nint b;",
            "int a;           \nint b;",
            [],
        )

    def test_block_comment_is_masked(self) -> None:
        self._assert_snapshot(
            "int a; /* hide */ int b;",
            "int a;            int b;",
            [],
        )

    def test_block_comment_spanning_lines_keeps_newlines(self) -> None:
        self._assert_snapshot(
            "int a; /* one\ntwo */ int b;",
            "int a;       \n       int b;",
            [],
        )

    def test_string_literal_is_masked(self) -> None:
        self._assert_snapshot(
            'x = "abc; def";',
            "x =           ;",
            [],
        )

    def test_character_literal_is_masked(self) -> None:
        self._assert_snapshot(
            "c = ';';",
            "c =    ;",
            [],
        )

    def test_escaped_quote_inside_string_is_masked(self) -> None:
        self._assert_snapshot(
            'x = "a\\"; b";',
            "x =         ;",
            [],
        )

    def test_escaped_quote_inside_character_literal_is_masked(self) -> None:
        self._assert_snapshot(
            "char c = '\\'';",
            "char c =     ;",
            [],
        )

    def test_newline_inside_string_reports_two_issues(self) -> None:
        self._assert_snapshot(
            'x = "abc\nb";',
            "x =     \nb  ",
            [
                ("Unterminated string literal.", 4, 8),
                ("Unterminated string literal.", 10, 12),
            ],
        )

    def test_unterminated_block_comment_reports_issue(self) -> None:
        self._assert_snapshot(
            "int a; /* never ends",
            "int a;              ",
            [("Unterminated block comment.", 7, 20)],
        )

    def test_unterminated_character_literal_reports_issue(self) -> None:
        self._assert_snapshot(
            "c = 'a",
            "c =   ",
            [("Unterminated character literal.", 4, 6)],
        )

    def test_mixed_comments_across_lines(self) -> None:
        self._assert_snapshot(
            "/* multi\nline */ // trailing\nint x;",
            "        \n                   \nint x;",
            [],
        )

    def test_escaped_backslash_at_end_of_string_leaves_literal_open(self) -> None:
        self._assert_snapshot(
            'x = "abc\\";',
            "x =        ",
            [("Unterminated string literal.", 4, 11)],
        )

    def test_empty_source_is_unchanged(self) -> None:
        self._assert_snapshot("", "", [])


if __name__ == "__main__":
    unittest.main()
