#!/usr/bin/env python3
"""应用启动入口。"""

import os
import sys
import traceback


project_root = os.path.dirname(os.path.abspath(__file__))
# 以脚本方式运行时，确保 `app` 包始终能被稳定导入。
sys.path.insert(0, project_root)

from app.controllers.application_controller import ApplicationController
from app.debug_logger import debug_logger


def main():
    """创建应用控制器并进入 Qt 事件循环。"""
    try:
        controller = ApplicationController()
        controller.run()
    except Exception as exc:
        debug_logger.log_exception("main", "startup", exc)
        print("应用启动失败，请查看 logs/latest_error_summary.md 或 latest_debug.log", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
