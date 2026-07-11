"""Architecture entrypoint for the responsibility-split unified frontend contracts."""

from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedFrontendContractArchitectureTests(unittest.TestCase):
    def test_domain_contract_modules_remain_explicit(self) -> None:
        tests_dir = Path(__file__).resolve().parent
        expected = {
            "test_unified_frontend_shell_contract.py",
            "test_unified_frontend_settings_contract.py",
            "test_unified_frontend_i18n_logs_contract.py",
            "test_unified_frontend_task_pages_contract.py",
            "test_unified_frontend_static_contract.py",
        }
        existing = {path.name for path in tests_dir.glob("test_unified_frontend_*_contract.py")}
        self.assertTrue(expected.issubset(existing))


if __name__ == "__main__":
    unittest.main()
