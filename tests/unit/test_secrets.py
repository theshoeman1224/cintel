import unittest

from cintel.utilities.secrets import (
    is_sensitive_name,
    redact_assignment_arguments,
    redact_value,
)


class SecretUtilityTests(unittest.TestCase):
    def test_detects_secret_names_without_redacting_unrelated_substrings(self) -> None:
        self.assertTrue(is_sensitive_name("API_TOKEN"))
        self.assertTrue(is_sensitive_name("PRIVATE_KEY"))
        self.assertFalse(is_sensitive_name("MONKEY_MODE"))
        self.assertFalse(is_sensitive_name("KEYSTONE_PATH"))

    def test_redacts_assignment_arguments_and_guidance_values(self) -> None:
        self.assertEqual(
            ("MODE=debug", "API_TOKEN=***REDACTED***", "make"),
            redact_assignment_arguments(("MODE=debug", "API_TOKEN=secret", "make")),
        )
        self.assertEqual("<SET_LOCALLY>", redact_value("PASSWORD", "secret", "<SET_LOCALLY>"))


if __name__ == "__main__":
    unittest.main()
