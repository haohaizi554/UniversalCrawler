"""UCrawl 进程入口与模式调度子包。

具体入口分别拥有各自的参数、生命周期和返回契约；CLI、Web、GUI、交互式引导
与测试入口并不共享同一个执行器或输入输出格式。本包只为源码运行补充项目根
目录，并重导出 ``entry.dispatcher`` 的模式枚举和便捷调用函数。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 源码直接运行 entry 模块时，确保项目包可从仓库根目录解析。
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 包级重导出保留 ``from entry import run_gui, run_web, run_cli`` 等调用方式。
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
