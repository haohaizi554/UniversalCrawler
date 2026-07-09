"""Playwright stealth script loading and injection helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

STEALTH_SCRIPT_PATH = Path(__file__).with_name("stealth.js")


@lru_cache(maxsize=1)
def load_stealth_script() -> str:
    """每进程只读取一次 stealth.js，避免高频创建 context 时重复 IO。"""
    return STEALTH_SCRIPT_PATH.read_text(encoding="utf-8")


def apply_stealth_to_context(context: Any) -> None:
    """在页面脚本运行前注入 stealth 逻辑；无效 context 直接忽略，方便测试替身。"""
    if context is None or not hasattr(context, "add_init_script"):
        return
    context.add_init_script(load_stealth_script())
