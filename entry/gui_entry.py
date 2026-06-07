"""UCrawl 桌面 GUI 入口（薄适配层）。

行业对齐（PyPA 规范）：
- 在 `pyproject.toml` 的 `[project.gui-scripts]` 中注册为 `ucrawl-gui` 命令
- Windows 上启动**不弹黑窗**（与 console_scripts 区别）
- 透传到 `app.controllers.application_controller.ApplicationController`

历史对应：原 `main.py` (44 行)

调用链：
    ucrawl-gui (gui_script) -> entry.gui_entry:main() -> ApplicationController.run()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _set_windows_app_user_model_id() -> None:
    """尽早设置 Windows AppUserModelID，避免任务栏图标分组取错。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ucp.crawler.v1")
    except (ImportError, AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    """GUI 入口：启动 PyQt6 桌面应用。

    Args:
        argv: 命令行参数（透传给 ApplicationController，保留向后兼容）

    Returns:
        退出码
    """
    import multiprocessing
    import traceback

    from app.controllers.application_controller import ApplicationController
    from app.debug_logger import debug_logger

    try:
        multiprocessing.freeze_support()
        _set_windows_app_user_model_id()
        controller = ApplicationController()
        controller.run()
        return 0
    except Exception as exc:
        debug_logger.log_exception("gui_entry", "startup", exc)
        sys.stderr.write("应用启动失败，请查看 logs/latest_error_summary.md 或 latest_debug.log\n")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
