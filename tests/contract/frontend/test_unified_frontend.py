"""Architecture entrypoint for the responsibility-split unified frontend contracts."""

from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedFrontendContractArchitectureTests(unittest.TestCase):
    def test_domain_contract_modules_remain_explicit(self) -> None:
        tests_dir = Path(__file__).resolve().parent
        expected = {
            "test_shell.py",
            "test_settings.py",
            "test_i18n_logs.py",
            "test_task_pages.py",
            "test_static.py",
        }
        existing = {path.name for path in tests_dir.glob("test_*.py")}
        self.assertTrue(expected.issubset(existing))


if __name__ == "__main__":
    unittest.main()
