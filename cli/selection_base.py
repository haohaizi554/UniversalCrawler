"""二次选择策略基类和规则选择实现。"""

from __future__ import annotations

import sys
from typing import Protocol


class SelectionStrategy(Protocol):
    """二次选择策略协议。

    Spider 调用 ask_user_selection(items) 时由本策略决定返回哪些索引。

    Attributes:
        策略名: 用于日志输出
    """

    @property
    def strategy_name(self) -> str:
        """策略名称。"""
        ...

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """决定选择哪些项目。

        Args:
            items: 候选项列表，每项通常包含 {"title": ..., "index": ...} 等
            prompt: 提示文本 (来自 spider 的 self.log 消息)

        Returns:
            选中的索引列表 (list[int])，或 None 表示取消
        """
        ...


def is_selection_strategy(obj) -> bool:
    """检查对象是否是有效的 SelectionStrategy 实例（duck-type check）。

    由于 SelectionStrategy 是 Protocol 且未 @runtime_checkable，
    isinstance() 会抛 TypeError。SDK/REST API 需要用 duck-type 判断。
    """
    return (
        obj is not None
        and hasattr(obj, "select")
        and hasattr(obj, "strategy_name")
        and callable(getattr(obj, "select", None))
    )


def _parse_index_list(s: str, max_count: int) -> list[int]:
    """解析逗号分隔的索引字符串，支持范围 (如 "0,2-5" 或 "0,2:5")。

    Args:
        s: 字符串如 "0,2,5" 或 "0,2-5" 或 "0,2:5"
        max_count: 最大有效索引 (越界会被丢弃)

    Returns:
        去重且排序的合法索引列表
    """
    indices = set()
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        # 支持 "-" 和 ":" 作为范围分隔符
        if ("-" in token or ":" in token) and not token.startswith("-") and not token.startswith(":"):
            sep = "-" if "-" in token else ":"
            a, b = token.split(sep, 1)
            try:
                start, end = int(a), int(b)
                for i in range(min(start, end), max(start, end) + 1):
                    if 0 <= i < max_count:
                        indices.add(i)
            except ValueError:
                continue
        else:
            try:
                i = int(token)
                if 0 <= i < max_count:
                    indices.add(i)
            except ValueError:
                continue
    return sorted(indices)


class RuleSelection(SelectionStrategy):
    """基于规则的策略：--select / --exclude / --all / --first / --last。

    规则按优先级应用：exclude > all/first/last > select。
    当 select=None 且没有其他规则时，默认全选。

    Attributes:
        select: 指定选中的索引（逗号分隔，支持范围）
        exclude: 指定排除的索引（逗号分隔，支持范围）
        all_items: 是否全选
        first: 是否只选第一个
        last: 是否只选最后一个
    """

    def __init__(
        self,
        select: str | None = None,
        exclude: str | None = None,
        all_items: bool = False,
        first: bool = False,
        last: bool = False,
    ):
        # 关键：不能用 self.select 命名属性，会覆盖下面的 select() 方法
        self._select_rule = select
        self.exclude = exclude
        self.all = all_items
        self.first = first
        self.last = last

    @property
    def strategy_name(self) -> str:
        return "rule"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """根据规则选择。"""
        n = len(items)
        if n == 0:
            return []

        # 1. 计算"基础集合"
        if self.first:
            base = [0]
        elif self.last:
            base = [n - 1]
        elif self.all or self._select_rule is None:
            base = list(range(n))
        else:
            base = _parse_index_list(self._select_rule, n)
            if not base:
                # select 解析后为空 → 默认全选
                base = list(range(n))

        # 2. 排除
        if self.exclude:
            excluded = set(_parse_index_list(self.exclude, n))
            base = [i for i in base if i not in excluded]

        return base


class AutoSelection:
    """自动选择：根据环境自动挑选合适的策略。

    优先级：
    1. 有 TTY → InteractiveTTYSelection
    2. stdin 非 TTY (管道) → PipeSelection
    3. 否则 → RuleSelection (all)

    Attributes:
        rule_kwargs: 传给 RuleSelection 的默认参数
    """

    def __init__(self, **rule_kwargs):
        self._rule = RuleSelection(**rule_kwargs)
        self._interactive = None  # 延迟导入
        self._pipe = None  # 延迟导入
        self._strategy: SelectionStrategy = self._detect()

    @property
    def strategy_name(self) -> str:
        return self._strategy.strategy_name

    def _detect(self) -> SelectionStrategy:
        """检测环境并选择策略。"""
        try:
            if sys.stdin.isatty():
                from cli.interactive import InteractiveTTYSelection
                return InteractiveTTYSelection()
        except (AttributeError, ValueError):
            pass

        try:
            if not sys.stdin.isatty():
                from cli.pipe import PipeSelection
                return PipeSelection()
        except (AttributeError, ValueError):
            pass

        return self._rule

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        return self._strategy.select(items, prompt)
