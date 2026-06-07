#!/usr/bin/env python3
"""UCrawl 顶层入口（向后兼容 + 自适应模式）。

行业对齐（参考 PyPA / cookiecutter-pypackage）：

- 这是 `python main.py` / `python -m ucrawl` 的入口
- 无参数时**自适应检测**模式（TTY/环境/依赖）
- 有参数时透传给对应 mode

历史：
- 原本 `main.py` 是 GUI 入口，现在改为**统一自适应入口**
- 原来的 GUI 启动方式已迁移到 `entry.gui_entry`（`ucrawl-gui` 命令 / `python GUI_entry.py`）
- 原来的 Web 启动方式已迁移到 `entry.web_entry`（`ucrawl-web` 命令 / `python web_entry.py`）
- 原来的 CLI 启动方式已迁移到 `entry.cli_entry`（`ucrawl` 命令 / `python cli_entry.py`）
- 原来的交互式启动方式已迁移到 `entry.interactive_entry`（`ucrawl-i` 命令 / `python interactive_entry.py`）
"""

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
