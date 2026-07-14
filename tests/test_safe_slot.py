from __future__ import annotations

import unittest
from unittest.mock import patch

from app.utils.safe_slot import safe_slot


class SafeSlotTests(unittest.TestCase):
    def test_exception_diagnostics_keep_types_and_redact_sensitive_kwargs(self) -> None:
        @safe_slot
        def fail(value: object, *, api_token: str, retry_count: int) -> None:
            raise ValueError("slot failed")

        with patch("app.utils.safe_slot.debug_logger.log_exception") as log_exception:
            result = fail(object(), api_token="top-secret", retry_count=3)

        self.assertIsNone(result)
        details = log_exception.call_args.kwargs["details"]
        self.assertEqual(details["arg_types"], ["object"])
        self.assertEqual(details["kwargs"]["api_token"], "<redacted>")
        self.assertEqual(details["kwargs"]["retry_count"], 3)


if __name__ == "__main__":
    unittest.main()
