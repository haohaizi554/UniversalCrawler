"""负责加载并注入 Playwright 隐匿脚本。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.utils.runtime_paths import resolve_resource_file

STEALTH_SCRIPT_RESOURCE = "app/core/anti_detection/stealth.js"
# 保留旧常量供外部诊断代码读取；实际加载时重新走统一解析器，方便冻结态测试替换 _MEIPASS。
STEALTH_SCRIPT_PATH = resolve_resource_file(STEALTH_SCRIPT_RESOURCE)


@lru_cache(maxsize=1)
def load_stealth_script() -> str:
    """每进程只读取一次 stealth.js，避免高频创建 context 时重复 IO。"""
    return resolve_resource_file(STEALTH_SCRIPT_RESOURCE).read_text(encoding="utf-8")


def apply_stealth_to_context(context: Any) -> None:
    """在页面脚本运行前注入 stealth 逻辑；无效 context 直接忽略，方便测试替身。"""
    if context is None or not hasattr(context, "add_init_script"):
        return
    context.add_init_script(load_stealth_script())
