"""课程作业与回归联调用的核心测试套件入口。

使用unittest.TestSuite批量运行测试文件，并使用BeautifulReport生成测试报告。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

#核心测试
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入BeautifulReport
try:
    from BeautifulReport import BeautifulReport
    HAS_BEAUTIFUL_REPORT = True
except ImportError:
    HAS_BEAUTIFUL_REPORT = False
    print("警告: 未安装BeautifulReport，将使用默认文本报告")
    print("安装命令: pip install BeautifulReport")

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
    """构建核心测试套件，逐模块加载并打印状态。"""
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module_name in CORE_TEST_MODULES:
        try:
            suite.addTests(loader.loadTestsFromName(module_name))
            print(f"✓ 已加载测试模块: {module_name}")
        except Exception as e:
            print(f"✗ 加载测试模块失败 {module_name}: {e}")
    return suite

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="课程作业核心测试套件")
    parser.add_argument("--report-dir", default="test_reports", help="报告输出目录")
    args = parser.parse_args()

    print("=" * 60)
    print("运行核心测试套件")
    print("=" * 60)

    suite = build_suite()
    test_count = suite.countTestCases()
    print(f"\n{'='*60}")
    print(f"共加载 {test_count} 个测试用例")
    print(f"{'='*60}\n")

    if test_count == 0:
        print("警告: 没有加载到任何测试用例")
        raise SystemExit(1)

    # 创建报告目录
    report_path = PROJECT_ROOT / args.report_dir
    report_path.mkdir(exist_ok=True)

    if HAS_BEAUTIFUL_REPORT:
        result = BeautifulReport(suite)
        result.report(
            filename='core_suite_test_report',
            description='课程作业核心测试套件报告',
            report_dir=str(report_path),
            theme='theme_default'
        )
        print(f"\n✓ 测试报告已生成: {report_path / 'core_suite_test_report.html'}")
        raise SystemExit(0 if result.wasSuccessful() else 1)
    else:
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
