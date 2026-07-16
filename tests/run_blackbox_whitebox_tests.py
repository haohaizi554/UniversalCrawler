"""Compatibility entrypoint mapping black-box/white-box terms to suites.

Black-box behavior is represented by the contract suite; white-box behavior is
represented by the unit suite. The mapping is structural and never contains a
curated file list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support.runner import format_summary, run_categories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行目录驱动的黑盒/白盒测试")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--blackbox", action="store_true", help="仅运行 contract 套件")
    selection.add_argument("--whitebox", action="store_true", help="仅运行 unit 套件")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    suite_ids = ["contract"] if args.blackbox else ["unit"] if args.whitebox else ["contract", "unit"]
    results = run_categories(suite_ids, verbose=args.verbose, no_failfast=True)
    print(format_summary(results))
    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
