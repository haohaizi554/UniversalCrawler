"""与宿主无关的二次选择协议。"""

from __future__ import annotations

from typing import Protocol


class SelectionStrategy(Protocol):
    """在不依赖 GUI、CLI 或 Web 宿主的情况下选择项目索引。"""

    @property
    def strategy_name(self) -> str:
        """供诊断使用的稳定策略标识。"""
        ...

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """返回选中索引；用户取消时返回 ``None``。"""
        ...


def is_selection_strategy(obj: object) -> bool:
    """判断 *obj* 是否满足选择策略协议。"""
    return (
        obj is not None
        and hasattr(obj, "select")
        and hasattr(obj, "strategy_name")
        and callable(getattr(obj, "select", None))
    )
