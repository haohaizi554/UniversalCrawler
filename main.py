from __future__ import annotations
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def main() -> int:
    """主入口：自适应模式选择 + 派发。"""
    from entry import run
    return run()

if __name__ == "__main__":
    sys.exit(main())
