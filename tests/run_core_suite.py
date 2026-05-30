"""课程作业与回归联调用的核心测试套件入口。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CORE_TEST_MODULES = [
    "tests.test_video_item",
    "tests.test_utils_filenames",
    "tests.test_runtime_paths",
    "tests.test_settings_builders",
    "tests.test_auth_service",
    "tests.test_debug_logger",
    "tests.test_file_service",
    "tests.test_downloaders",
    "tests.test_download_manager_dispatch",
    "tests.test_application_controller",
    "tests.test_integration_flows",
    "tests.test_spider_helpers",
    "tests.test_main_entry",
]


def build_suite() -> unittest.TestSuite:
    """构建 `suite` 对应的结果、参数或对象。"""
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module_name in CORE_TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(build_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
