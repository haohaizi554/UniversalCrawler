"""Coursework suite runner with BeautifulReport output."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from BeautifulReport import BeautifulReport


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_DIR = PROJECT_ROOT / "coursework" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def build_suite() -> unittest.TestSuite:
    """构建 `suite` 对应的结果、参数或对象。"""
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromName("coursework.unit_tests.test_ddt_units"))
    suite.addTests(loader.loadTestsFromName("tests.test_runtime_paths"))
    return suite


def run() -> int:
    """执行当前对象或脚本的主流程。"""
    suite = build_suite()
    result = BeautifulReport(suite)
    filename = "beautiful_report"
    report_path = REPORT_DIR / f"{filename}.html"
    result.report(
        description="课程作业单元测试报告",
        filename=filename,
        report_dir=str(REPORT_DIR),
        theme="theme_default",
    )
    print(f"BeautifulReport generated: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
