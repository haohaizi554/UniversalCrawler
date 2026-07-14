"""二次选择策略基类和规则选择实现。"""

from __future__ import annotations

import logging
import re
import sys
from types import MethodType
from typing import Any, Callable

from shared.selection_base import SelectionStrategy, is_selection_strategy

_EXTERNAL_STRATEGY_BUILDERS: dict[str, Callable[[], Any]] = {}
_RESERVED_EXTENSION_STRATEGIES = ("interactive", "gui", "pipe")
_INDEX_TOKEN_PATTERN = re.compile(r"^-?\d+$")
_INDEX_RANGE_PATTERN = re.compile(r"^\d+[-:]\d+$")

def _build_interactive_strategy():
    from shared.interactive_selection import InteractiveTTYSelection

    return InteractiveTTYSelection()

def _build_pipe_strategy(*, preloaded_choices: list[list[int]] | None = None):
    from shared.pipe_selection import PipeSelection

    return PipeSelection(preloaded_choices=preloaded_choices)

def register_selection_strategy(name: str, builder: Callable[[], Any]) -> None:
    """注册扩展选择策略构造器。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("策略名称不能为空")
    if not callable(builder):
        raise TypeError("策略构造器必须可调用")
    _EXTERNAL_STRATEGY_BUILDERS[name.strip()] = builder

def get_registered_selection_strategy_names() -> list[str]:
    return sorted(_EXTERNAL_STRATEGY_BUILDERS.keys())

def _build_extension_strategy(name: str):
    if name == "interactive":
        return _build_interactive_strategy()
    if name == "pipe":
        return _build_pipe_strategy()
    builder = _EXTERNAL_STRATEGY_BUILDERS.get(name)
    if builder is None:
        raise ValueError(
            f"选择策略 {name} 未注册。可用扩展策略: {', '.join(get_registered_selection_strategy_names()) or '无'}"
        )
    return builder()

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

def _validate_index_rule(rule: str | None, *, name: str) -> None:
    """Reject malformed explicit rules before a crawler can start."""
    if rule is None:
        return
    if not isinstance(rule, str):
        raise TypeError(f"{name} 规则必须是字符串或 None")
    if not rule.strip():
        raise ValueError(f"{name} 规则不能为空")
    for raw_token in rule.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if _INDEX_TOKEN_PATTERN.fullmatch(token) or _INDEX_RANGE_PATTERN.fullmatch(token):
            continue
        raise ValueError(f"{name} 规则包含无效索引: {token}")

def normalize_preloaded_choices(choices: object) -> list[list[int]]:
    """Validate the SDK/pipe two-dimensional selection payload."""
    if not isinstance(choices, list):
        raise TypeError("preload 的 choices 必须是二维数组")
    normalized: list[list[int]] = []
    for round_index, round_choices in enumerate(choices):
        if not isinstance(round_choices, list):
            raise TypeError(f"preload 的 choices[{round_index}] 必须是数组")
        normalized_round: list[int] = []
        for choice_index, value in enumerate(round_choices):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"preload 的 choices[{round_index}][{choice_index}] 必须是整数"
                )
            if value < 0:
                raise ValueError(
                    f"preload 的 choices[{round_index}][{choice_index}] 不能为负数"
                )
            normalized_round.append(value)
        normalized.append(normalized_round)
    return normalized

def parse_preloaded_choices(rule: str) -> list[list[int]]:
    """Parse the CLI ``0|1,2||3`` syntax without swallowing typos."""
    if not isinstance(rule, str) or not rule.strip():
        raise ValueError("--preload-choices 不能为空")
    rounds: list[list[int]] = []
    for round_index, token in enumerate(rule.split("|")):
        values: list[int] = []
        for raw_value in token.split(","):
            value = raw_value.strip()
            if not value:
                continue
            if not value.isdigit():
                raise ValueError(
                    f"--preload-choices 第 {round_index + 1} 轮包含无效索引: {value}"
                )
            values.append(int(value))
        rounds.append(values)
    return rounds

def build_selection_prompt(selection_round: int, item_count: int) -> str:
    """构建统一的二次选择提示文案。"""
    return f"二次选择 #{selection_round}: {item_count} 个候选"

def format_selection_result(indices: list[int], preview_limit: int = 10) -> str:
    """格式化统一的二次选择结果摘要。"""
    preview = indices[:preview_limit]
    suffix = "..." if len(indices) > preview_limit else ""
    return f"  → 选中 {len(indices)} 项: {preview}{suffix}"

class SelectionBridge:
    """把 SelectionStrategy 桥接为 spider 可直接调用的同步选择入口。"""

    def __init__(
        self,
        strategy: SelectionStrategy,
        *,
        on_prompt: Callable[[str, list], None] | None = None,
        on_result: Callable[[str, list[int], bool, list], None] | None = None,
        on_error: Callable[[Exception, str, list], None] | None = None,
        fallback_to_all: bool = True,
    ) -> None:
        self.strategy = strategy
        self.on_prompt = on_prompt
        self.on_result = on_result
        self.on_error = on_error
        self.fallback_to_all = fallback_to_all
        self.selection_count = 0

    def select(self, items: list) -> tuple[str, list[int], bool]:
        """执行一次同步选择，统一处理 prompt、异常兜底与取消语义。"""
        self.selection_count += 1
        prompt = build_selection_prompt(self.selection_count, len(items))
        if self.on_prompt:
            self.on_prompt(prompt, items)
        try:
            indices = self.strategy.select(items, prompt=prompt)
        except Exception as exc:
            logging.getLogger(__name__).warning("选择策略执行失败，返回空选择: %s", exc)
            if self.on_error:
                self.on_error(exc, prompt, items)
            indices = list(range(len(items))) if self.fallback_to_all else []
        cancelled = indices is None
        normalized = [] if cancelled else list(indices)
        if self.on_result:
            self.on_result(prompt, normalized, cancelled, items)
        return prompt, normalized, cancelled

    def build_sync_ask_user_selection(self):
        """生成可直接 monkey-patch 到 spider 上的同步 ask_user_selection。"""
        bridge = self

        def ask_user_selection_sync(spider_self, items):
            _prompt, indices, _cancelled = bridge.select(items)
            return indices

        return ask_user_selection_sync

    def bind_sync(self, spider) -> None:
        """把同步桥接逻辑挂到 spider.ask_user_selection。"""
        spider.ask_user_selection = MethodType(self.build_sync_ask_user_selection(), spider)

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
        _validate_index_rule(select, name="select")
        _validate_index_rule(exclude, name="exclude")
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
                raise ValueError(f"select 规则没有命中有效范围 0-{n - 1}: {self._select_rule}")

        # 2. 排除
        if self.exclude:
            excluded = set(_parse_index_list(self.exclude, n))
            if not excluded:
                raise ValueError(f"exclude 规则没有命中有效范围 0-{n - 1}: {self.exclude}")
            base = [i for i in base if i not in excluded]

        return base

class SelectionStrategyFactory:
    """统一构造 CLI / Web / SDK 使用的二次选择策略。"""

    @staticmethod
    def _rule_from_mapping(mapping: dict[str, Any]) -> RuleSelection:
        select_val = mapping.get("select")
        exclude_val = mapping.get("exclude")
        if select_val is not None and not isinstance(select_val, str):
            raise TypeError("rule 策略的 select 必须是字符串或 null")
        if exclude_val is not None and not isinstance(exclude_val, str):
            raise TypeError("rule 策略的 exclude 必须是字符串或 null")
        return RuleSelection(
            select=select_val,
            exclude=exclude_val,
            all_items=bool(mapping.get("all_items", False)),
            first=bool(mapping.get("first", False)),
            last=bool(mapping.get("last", False)),
        )

    @staticmethod
    def parse_preloaded_choices(raw: str | list | tuple | None) -> list[list[int]]:
        """解析 CLI / API 使用的 preload 选择配置。"""
        if raw is None:
            return []
        if isinstance(raw, str):
            return parse_preloaded_choices(raw)
        return normalize_preloaded_choices(raw)

    @classmethod
    def _default_strategy(cls, default_strategy: str):
        if default_strategy == "all":
            return RuleSelection(all_items=True)
        if default_strategy == "interactive":
            return _build_extension_strategy("interactive")
        if default_strategy == "pipe":
            return _build_extension_strategy("pipe")
        if default_strategy == "rule_all":
            return RuleSelection(all_items=True)
        return AutoSelection()

    @staticmethod
    def available_strategy_names() -> list[str]:
        names = ["all", "first", "last", "rule", "preload"]
        for name in _RESERVED_EXTENSION_STRATEGIES:
            if name in {"interactive", "pipe"} or name in _EXTERNAL_STRATEGY_BUILDERS:
                names.append(name)
        return names

    @classmethod
    def from_cli_args(cls, args, *, default_strategy: str = "rule_all"):
        """从 argparse.Namespace 统一构造 CLI 选择策略。"""
        if getattr(args, "interactive", False):
            return _build_interactive_strategy()
        if getattr(args, "pipe", False):
            return _build_pipe_strategy()

        preload_choices = getattr(args, "preload_choices", None)
        if preload_choices:
            return _build_pipe_strategy(preloaded_choices=cls.parse_preloaded_choices(preload_choices))

        has_rule = any(
            (
                getattr(args, "select", None),
                getattr(args, "exclude", None),
                getattr(args, "select_all", False),
                getattr(args, "first", False),
                getattr(args, "last", False),
            )
        )
        if has_rule or default_strategy == "rule_all":
            return RuleSelection(
                select=getattr(args, "select", None),
                exclude=getattr(args, "exclude", None),
                all_items=bool(getattr(args, "select_all", False) or getattr(args, "select", None) is None),
                first=getattr(args, "first", False),
                last=getattr(args, "last", False),
            )
        return cls._default_strategy(default_strategy)

    @classmethod
    def from_value(cls, selection, *, default_strategy: str = "auto"):
        """从 SDK / Web 的 selection 值统一构造策略。"""
        if selection is None:
            return cls._default_strategy(default_strategy)
        if is_selection_strategy(selection):
            return selection
        if isinstance(selection, str):
            if selection == "all":
                return RuleSelection(all_items=True)
            if selection == "first":
                return RuleSelection(first=True)
            if selection == "last":
                return RuleSelection(last=True)
            if selection == "interactive":
                return _build_extension_strategy("interactive")
            if selection == "gui":
                return _build_extension_strategy("gui")
            if selection == "pipe":
                return _build_extension_strategy("pipe")
            return RuleSelection(select=selection)
        if isinstance(selection, (list, tuple)):
            return _build_pipe_strategy(preloaded_choices=[list(selection)])
        if isinstance(selection, dict):
            strategy_name = selection.get("strategy")
            if strategy_name:
                if strategy_name == "all":
                    return RuleSelection(all_items=True)
                if strategy_name == "first":
                    return RuleSelection(first=True)
                if strategy_name == "last":
                    return RuleSelection(last=True)
                if strategy_name == "rule":
                    return cls._rule_from_mapping(selection)
                if strategy_name == "preload":
                    raw_choices = selection.get("choices", [])
                    if isinstance(raw_choices, str):
                        raise TypeError("preload 的 choices 必须是二维数组")
                    return _build_pipe_strategy(preloaded_choices=cls.parse_preloaded_choices(raw_choices))
                if strategy_name == "interactive":
                    return _build_extension_strategy("interactive")
                if strategy_name == "gui":
                    return _build_extension_strategy("gui")
                if strategy_name == "pipe":
                    return _build_extension_strategy("pipe")
                raise ValueError(
                    f"无效选择策略: {strategy_name}。支持: {', '.join(cls.available_strategy_names())}"
                )
            return cls._rule_from_mapping(selection)
        raise TypeError(f"无法解析 selection 参数: {type(selection).__name__}")

    @classmethod
    def from_web_payload(cls, selection_dict: dict | None):
        """从 Web 端 payload 构造策略；非法输入返回 None，便于 API 层统一报错。"""
        try:
            return cls.from_value(selection_dict, default_strategy="all")
        except (TypeError, ValueError):
            return None

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
                return _build_interactive_strategy()
        except (AttributeError, ValueError):
            pass

        try:
            if not sys.stdin.isatty():
                return _build_pipe_strategy()
        except (AttributeError, ValueError):
            pass

        return self._rule

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        return self._strategy.select(items, prompt)
