"""打包辅助脚本，负责 `packaging/runtime_hook.py` 相关的构建、发布或运行时处理。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_bundle_root() -> Path:
    """提供 `_resolve_bundle_root` 对应的内部辅助逻辑。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


bundle_root = _resolve_bundle_root()
browser_root = bundle_root / "ms-playwright"
if browser_root.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
