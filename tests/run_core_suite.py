"""Compatibility entrypoint for the canonical unit and integration suites."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support.runner import format_summary, run_categories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行目录驱动的核心测试套件")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示完整 pytest 节点")
    parser.add_argument("--failfast", action="store_true", help="首个失败后停止")
    args = parser.parse_args(argv)

    results = run_categories(
        ["unit", "integration"],
        verbose=args.verbose,
        no_failfast=not args.failfast,
    )
    print(format_summary(results))
    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
