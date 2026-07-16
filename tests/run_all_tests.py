#!/usr/bin/env python3
"""全量测试运行脚本（CLI 版本）。

从 ``tests/support/catalog.py`` 读取套件目录，按套件或插件分类生成报告。
新代码请优先用 ``tests/launcher.py``（三模：GUI/TUI/CLI）。

使用方法：
    # 全量
    python tests/run_all_tests.py

    # 按套件
    python tests/run_all_tests.py --category unit
    python tests/run_all_tests.py --category contract
    python tests/run_all_tests.py --category all
    python tests/run_all_tests.py --category e2e

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


# 让 tests.support catalog / runner 可被 import
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def main():
    parser = argparse.ArgumentParser(
        description="全量测试运行脚本（基于目录 catalog）",
    )
    parser.add_argument(
        "--category",
        choices=None,  # 延后填充
        help="测试套件或插件分类 ID（默认 all）",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用套件与插件分类",
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

    # 延后导入（让 --help 不依赖测试 catalog）
    from tests.support.catalog import (
        get_enabled_categories,
        get_resolved_files,
        get_category,
    )
    from tests.support.runner import run_category, format_summary, TestResult

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

    # 决定要跑的套件或插件分类
    if args.category is None or args.category == "all":
        target_ids = [c.id for c in get_enabled_categories() if c.id != "all"]
    else:
        target_ids = [args.category]

    print("=" * 70)
    print(f"全量测试运行 - 套件: {' / '.join(target_ids)}")
    print("=" * 70)

    # 逐套件运行
    results: list[TestResult] = []
    for cid in target_ids:
        cat = get_category(cid)
        files = get_resolved_files(cid)
        print(f"\n[套件] {cid}: {cat.name}")
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
        print(f"\n❌ 有 {sum(1 for r in results if not r.success)} 个套件失败")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
