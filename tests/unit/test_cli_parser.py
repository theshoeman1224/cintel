import contextlib
import io
import unittest

from cintel.cli.main import build_parser


class CLIParserTests(unittest.TestCase):
    def test_help_documents_global_option_placement(self) -> None:
        text = build_parser().format_help()
        self.assertIn("must come before the subcommand", text)

    def test_help_documents_previously_bare_options(self) -> None:
        text = build_parser().format_help()
        for option in (
            "--non-interactive",
            "--verbose",
            "--makefile",
            "--make-working-directory",
            "--target",
            "--build-config",
            "--force-build-discovery",
            "--respect-make-timestamps",
            "--input-file",
        ):
            self.assertIn(option, text)
        self.assertIn("default: default", text)

    def test_init_repository_positional_is_optional(self) -> None:
        args = build_parser().parse_args(["init"])
        self.assertIsNone(args.repository_path)

    def test_budget_rejects_zero_with_actionable_message(self) -> None:
        stderr = io.StringIO()
        with (
            self.assertRaises(SystemExit) as caught,
            contextlib.redirect_stderr(stderr),
        ):
            build_parser().parse_args(
                ["context", "function", "foo", "--budget", "0"]
            )
        self.assertEqual(2, caught.exception.code)
        self.assertIn("must be a positive integer", stderr.getvalue())

    def test_budget_rejects_non_numeric_values(self) -> None:
        stderr = io.StringIO()
        with (
            self.assertRaises(SystemExit) as caught,
            contextlib.redirect_stderr(stderr),
        ):
            build_parser().parse_args(
                ["context", "function", "foo", "--budget", "abc"]
            )
        self.assertEqual(2, caught.exception.code)
        self.assertIn("must be an integer", stderr.getvalue())

    def test_build_config_default_is_default(self) -> None:
        args = build_parser().parse_args(["build", "units"])
        self.assertEqual("default", args.build_config)


if __name__ == "__main__":
    unittest.main()
