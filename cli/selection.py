"""二次选择策略模块。

提供 5 种策略：
- RuleSelection：基于规则 (--select/--exclude/all/first/last)
- InteractiveTTYSelection：TTY 交互 (用户在终端输入逗号分隔的索引)
- GUISelection：GUI 弹窗 (复用 SelectionDialog，与 GUI 体验一致)
- PipeSelection：stdin 管道 (从 stdin 读 JSON 列表)
- AutoSelection：自动选择 (有 TTY → 交互，否则管道，再否则规则)

向后兼容：旧的导入路径仍然有效。
"""

from __future__ import annotations

from cli.selection_base import (
    SelectionStrategy,
    RuleSelection,
    AutoSelection,
    is_selection_strategy,
)
from cli.interactive import InteractiveTTYSelection
from cli.gui_selection import GUISelection
from cli.pipe import PipeSelection, PipeOutput

__all__ = [
    "SelectionStrategy",
    "RuleSelection",
    "InteractiveTTYSelection",
    "GUISelection",
    "PipeSelection",
    "PipeOutput",
    "AutoSelection",
    "is_selection_strategy",
]
