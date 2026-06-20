"""
作者：从不内卷的好孩子
"""
"""课程作业黑盒白盒测试(单元测试）入口。

使用unittest.TestSuite批量运行测试文件，并使用BeautifulReport生成测试报告。
"""

import sys
import os
import unittest
from pathlib import Path

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入BeautifulReport
try:
    from BeautifulReport import BeautifulReport
    HAS_BEAUTIFUL_REPORT = True
except ImportError:
    HAS_BEAUTIFUL_REPORT = False
    print("警告: 未安装BeautifulReport，将使用默认文本报告")
    print("安装命令: pip install BeautifulReport")

# 黑盒测试模块（BB-001 ~ BB-010）
BLACKBOX_TEST_MODULES = [
    "tests.test_utils_filenames",           # BB-001, BB-002
    "tests.test_video_item",                # BB-003
    "tests.test_spider_helpers",            # BB-004, BB-005
    "tests.test_settings_builders",         # BB-006, BB-007
    "tests.test_auth_service",              # BB-008
    "tests.test_file_service",              # BB-009
    "tests.test_application_controller",    # BB-010
]

# 白盒测试模块（WB-001 ~ WB-008）
WHITEBOX_TEST_MODULES = [
    "tests.test_runtime_paths",             # WB-001, WB-002
    "tests.test_main_entry",                # WB-003, WB-004
    "tests.test_download_manager_dispatch", # WB-005, WB-006, WB-007
    "tests.test_debug_logger",              # WB-008
]

def load_tests_from_modules(module_names: list) -> unittest.TestSuite:
    """从模块名称列表加载测试到TestSuite。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    for module_name in module_names:
        try:
            # 使用loadTestsFromName加载模块中的所有测试
            tests = loader.loadTestsFromName(module_name)
            suite.addTests(tests)
            print(f"✓ 已加载测试模块: {module_name}")
        except Exception as e:
            print(f"✗ 加载测试模块失败 {module_name}: {e}")
    
    return suite

def run_tests_with_suite(test_modules: list, report_dir: str = "test_reports") -> int:
    suite = load_tests_from_modules(test_modules)
    # 获取测试数量
    test_count = suite.countTestCases()
    print(f"\n{'='*60}")
    print(f"共加载 {test_count} 个测试用例")
    print(f"{'='*60}\n")
    
    if test_count == 0:
        print("警告: 没有加载到任何测试用例")
        return 1
    # 创建报告目录
    report_path = PROJECT_ROOT / report_dir
    report_path.mkdir(exist_ok=True)
    
    # 使用BeautifulReport生成报告
    if HAS_BEAUTIFUL_REPORT:
        result = BeautifulReport(suite)
        result.report(
            filename='blackbox_whitebox_test_report',
            description='课程作业黑盒白盒测试报告',
            report_dir=str(report_path),
            theme='theme_default'
        )
        print(f"\n✓ 测试报告已生成: {report_path / 'blackbox_whitebox_test_report.html'}")
        # BeautifulReport.run()返回None，我们需要通过wasSuccessful判断
        return 0 if result.wasSuccessful() else 1
    else:
        # 使用默认的TextTestRunner
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="课程作业黑盒白盒测试(单元测试）")
    parser.add_argument("--blackbox", action="store_true", help="仅执行黑盒测试")
    parser.add_argument("--whitebox", action="store_true", help="仅执行白盒测试")
    parser.add_argument("--report-dir", default="test_reports", help="报告输出目录")
    args = parser.parse_args()

    if args.blackbox:
        test_modules = BLACKBOX_TEST_MODULES
        print("=" * 60)
        print("运行黑盒测试 (BB-001 ~ BB-010)")
        print("=" * 60)
    elif args.whitebox:
        test_modules = WHITEBOX_TEST_MODULES
        print("=" * 60)
        print("运行白盒测试 (WB-001 ~ WB-008)")
        print("=" * 60)
    else:
        test_modules = BLACKBOX_TEST_MODULES + WHITEBOX_TEST_MODULES
        print("=" * 60)
        print("运行全部黑盒和白盒测试")
        print("=" * 60)

    exit_code = run_tests_with_suite(test_modules, args.report_dir)
    raise SystemExit(exit_code)
