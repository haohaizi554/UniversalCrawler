#!/usr/bin/env python3
"""全量测试运行脚本（CLI 版本）。

从 ``tests/test_registry.py`` 读取注册表，按类别生成报告。
新代码请优先用 ``tests/test_launcher.py``（三模：GUI/TUI/CLI）。

使用方法：
    # 全量
    python tests/run_all_tests.py

    # 按类别
    python tests/run_all_tests.py --category cli_sdk
    python tests/run_all_tests.py --category all
    python tests/run_all_tests.py --category browser_e2e

    # 详细输出
    python tests/run_all_tests.py --verbose

    # 不遇失败停止
    python tests/run_all_tests.py --no-failfast
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError):
                pass

_configure_console_output()


# 让 test_registry / test_runner 可被 import
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

def main():
    parser = argparse.ArgumentParser(
        description="全量测试运行脚本（基于 test_registry）",
    )
    parser.add_argument(
        "--category",
        choices=None,  # 延后填充
        help="测试类别 ID（默认 all）",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用类别",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )
    parser.add_argument(
        "--no-failfast",
        action="store_true",
        help="遇失败不停止",
    )

    args = parser.parse_args()

    # 延后导入（让 --help 不依赖 test_registry）
    from test_registry import (
        get_enabled_categories,
        get_resolved_files,
        get_category,
    )
    from test_runner import run_category, format_summary, TestResult

    # 填充 choices
    cat_ids = [c.id for c in get_enabled_categories()]
    if args.category is None:
        # argparse 在第一次 parse 时不支持动态 choices，这里手动验证
        pass
    else:
        if args.category not in cat_ids:
            parser.error(
                f"unknown category: {args.category}. "
                f"Available: {', '.join(cat_ids)}"
            )

    if args.list:
        print(f"{'ID':<14} {'名称':<14} {'文件':<6} {'GUI':<5} {'网络':<5} 描述")
        print("-" * 90)
        for c in get_enabled_categories():
            gui = "✓" if c.requires_gui else " "
            net = "✓" if c.requires_network else " "
            print(
                f"{c.id:<14} {c.name:<14} "
                f"{c.file_count():<6} {gui:<5} {net:<5} {c.description}"
            )
        return 0

    # 决定要跑的类别
    if args.category is None or args.category == "all":
        target_ids = [c.id for c in get_enabled_categories() if c.id != "all"]
    else:
        target_ids = [args.category]

    print("=" * 70)
    print(f"全量测试运行 - 类别: {' / '.join(target_ids)}")
    print("=" * 70)

    # 逐类别运行
    results: list[TestResult] = []
    for cid in target_ids:
        cat = get_category(cid)
        files = get_resolved_files(cid)
        print(f"\n[类别] {cid}: {cat.name}")
        print(f"  描述: {cat.description}")
        print(f"  文件: {len(files)} 个")
        res = run_category(
            category_id=cid,
            category_name=cat.name,
            files=files,
            verbose=args.verbose,
            no_failfast=args.no_failfast,
        )
        results.append(res)
        status = "✓ PASSED" if res.success else "✗ FAILED"
        print(
            f"  结果: {status} "
            f"(P={res.passed} F={res.failed} S={res.skipped} E={res.errors}, "
            f"{res.duration:.2f}s)"
        )

    # 汇总
    print()
    print(format_summary(results))
    all_ok = all(r.success for r in results)
    if all_ok:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n❌ 有 {sum(1 for r in results if not r.success)} 个类别失败")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
