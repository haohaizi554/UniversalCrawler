from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_bundle_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


bundle_root = _resolve_bundle_root()
browser_root = bundle_root / "ms-playwright"
if browser_root.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
