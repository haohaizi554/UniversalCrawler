"""修正 PyInstaller 冻结进程的标准流与 Windows 应用标识。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller console=False 时 sys.stdout / sys.stderr 为 None，
# 会导致 uvicorn 等库调用 .isatty() 时崩溃，这里提供兜底。
class _NullStream:
    """模拟 sys.stdout/stderr 的最小接口，写入内容直接丢弃。"""

    def write(self, *args, **kwargs):
        pass

    def flush(self, *args, **kwargs):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("fileno not available on NullStream")

if sys.stdout is None:
    sys.stdout = _NullStream()  # type: ignore[assignment]
if sys.stderr is None:
    sys.stderr = _NullStream()  # type: ignore[assignment]

def _resolve_bundle_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent

bundle_root = _resolve_bundle_root()
browser_root = bundle_root / "ms-playwright"
if browser_root.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))

# Windows shell 按可执行文件分配不同 AppUserModelID：Web 门户与主程序保持
# 独立任务栏分组，其他冻结入口使用通用 ID。
if os.name == "nt":
    try:
        import ctypes
        exe_name = Path(sys.executable).name.lower() if getattr(sys, "frozen", False) else ""
        if "crawlerwebportal" in exe_name:
            app_id = "ucrawl.universalcrawlerpro.web"
        elif "universalcrawlerpro" in exe_name:
            app_id = "ucrawl.universalcrawlerpro.main"
        else:
            app_id = "ucrawl.universalcrawlerpro.app"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass  # Shell 标识是可选集成，设置失败不得阻断冻结应用启动。
