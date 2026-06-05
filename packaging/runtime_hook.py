"""打包辅助脚本，负责 `packaging/runtime_hook.py` 相关的构建、发布或运行时处理。"""

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
    """提供 `_resolve_bundle_root` 对应的内部辅助逻辑。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


bundle_root = _resolve_bundle_root()
browser_root = bundle_root / "ms-playwright"
if browser_root.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
