"""二次选择策略模块。

提供 4 种策略：
- RuleSelection：基于规则 (--select/--exclude/all/first/last)
- InteractiveTTYSelection：TTY 交互 (用户在终端输入逗号分隔的索引)
- PipeSelection：stdin 管道 (从 stdin 读 JSON 列表)
- AutoSelection：自动选择 (有 TTY → 交互，否则管道，再否则规则)

向后兼容：旧的导入路径仍然有效。
"""

from __future__ import annotations

from cli.selection_base import (
    SelectionStrategy,
    RuleSelection,
    AutoSelection,
)
from cli.interactive import InteractiveTTYSelection
from cli.pipe import PipeSelection, PipeOutput

__all__ = [
    "SelectionStrategy",
    "RuleSelection",
    "InteractiveTTYSelection",
    "PipeSelection",
    "PipeOutput",
    "AutoSelection",
]
