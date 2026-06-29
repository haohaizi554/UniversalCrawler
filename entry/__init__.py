"""UCrawl 统一入口子包。

本子包提供多种调用模式的入口模块，每个模块都是一个**薄入口**，
只负责做"参数解析 → 模式编排 → 派发到 controller/cli"三件事。

行业对齐（参考 PyPA 官方 entry_points 规范）：

- `cli_entry.py`     -> console_scripts  (CLI 命令)
- `interactive_entry.py` -> console_scripts (交互式引导)
- `web_entry.py`     -> console_scripts  (Web 服务)
- `gui_entry.py`     -> gui_scripts      (Windows 上启动不弹黑窗)

所有入口最终都会：
1. 确保 sys.path 包含项目根目录
2. 复用同一个 controller / CLIRunner 实例
3. 输入输出格式完全一致（已与 GUI 对齐）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 关键：把项目根目录加进 sys.path，使 `from app.xxx import yyy` 始终可用
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 导出统一入口函数（让外部包级引用 `from entry import run_gui, run_web, run_cli` 也可用）
from entry.dispatcher import (  # noqa: E402
    Mode,
    detect_mode,
    run,
    run_cli,
    run_gui,
    run_interactive,
    run_test,
    run_web,
)

__all__ = [
    "Mode",
    "detect_mode",
    "run",
    "run_cli",
    "run_gui",
    "run_interactive",
    "run_test",
    "run_web",
]
