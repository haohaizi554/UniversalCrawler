"""Python 模块入口：`python -m cli` 或 `python cli_entry.py`。

这是 CLI 的官方入口点。
"""

from __future__ import annotations

import os
import sys

# 确保项目根目录在 sys.path 中
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
