"""TTY 交互式选择模块。

在终端显示候选列表，用户输入逗号分隔的索引进行选择。
支持快捷键：a=全选，n=不选，q=取消。
"""

from __future__ import annotations

import sys
from typing import Protocol

from cli.selection_base import SelectionStrategy

class InteractiveTTYSelection(SelectionStrategy):
    """TTY 交互式选择策略。

    在终端显示候选列表，提示用户输入逗号分隔的索引。
    输入 q / 空 → 取消
    输入 a → 全选
    输入 n → 不选
    输入 "0,2,5" → 选中 0/2/5

    Attributes:
        input_stream: 输入流（默认 sys.stdin）
        output_stream: 输出流（默认 sys.stderr）
    """

    def __init__(self, input_stream=None, output_stream=None):
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stderr

    @property
    def strategy_name(self) -> str:
        return "interactive"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """执行交互式选择。"""
        n = len(items)
        if n == 0:
            return []

        self._print_items(items, prompt)

        try:
            line = self.input.readline()
        except (EOFError, KeyboardInterrupt):
            return None

        if not line:
            return None

        line = line.strip().lower()
        if line in ("q", "quit", "exit", ""):
            return None
        if line in ("a", "all"):
            return list(range(n))
        if line in ("n", "none", "skip"):
            return []

        return self._parse_index_list(line, n)

    def _print_items(self, items: list, prompt: str) -> None:
        """打印候选列表。"""
        self.output.write("\n" + "=" * 60 + "\n")
        if prompt:
            self.output.write(f"🔔 {prompt}\n")
        self.output.write(f"📋 共 {len(items)} 个候选项：\n")
        group_title = self._shared_group_title(items)
        if group_title:
            self.output.write(f"📦 当前分组: {group_title}\n")
        for i, item in enumerate(items):
            title, subtitle = self._format_item_line(item, group_title)
            self.output.write(f"  [{i + 1}] {title}\n")
            if subtitle:
                self.output.write(f"      {subtitle}\n")
        self.output.write("=" * 60 + "\n")
        self.output.write("请输入要下载的索引 (从 1 开始，如 1,3,6) [a=全选/n=不选/q=取消]: ")
        self.output.flush()

    @staticmethod
    def _shared_group_title(items: list) -> str:
        """如果所有候选都属于同一分组，则只在顶部显示一次。"""
        titles = []
        for item in items:
            if not isinstance(item, dict):
                return ""
            title = str(item.get("group_title", "") or "").strip()
            if not title:
                return ""
            titles.append(title)
        if not titles:
            return ""
        first = titles[0]
        return first if all(title == first for title in titles) else ""

    @staticmethod
    def _format_item_line(item, shared_group_title: str) -> tuple[str, str]:
        """格式化单个候选项显示。"""
        if isinstance(item, dict):
            title = str(item.get("title", "未知"))
            subtitle = str(item.get("subtitle", "") or "").strip()
            if shared_group_title and title.startswith(shared_group_title):
                trimmed = title[len(shared_group_title):].lstrip(" ·-/")
                if trimmed:
                    title = trimmed
            return title, subtitle
        if hasattr(item, "title"):
            return str(getattr(item, "title", "未知")), ""
        return str(item), ""

    def _parse_index_list(self, s: str, max_count: int) -> list[int]:
        """解析逗号分隔的索引字符串，支持范围 (如 "1,3-6" 或 "1,3:6")。

        默认按 1 基索引解释，兼容历史 0 基输入。
        """
        one_based = self._should_use_one_based(s)
        indices = set()
        for token in s.split(","):
            token = token.strip()
            if not token:
                continue
            # 支持 "-" 和 ":" 作为范围分隔符（与 selection_base._parse_index_list 对齐）
            if ("-" in token or ":" in token) and not token.startswith("-") and not token.startswith(":"):
                sep = "-" if "-" in token else ":"
                a, b = token.split(sep, 1)
                try:
                    start, end = self._normalize_index(int(a), one_based), self._normalize_index(int(b), one_based)
                    for i in range(min(start, end), max(start, end) + 1):
                        if 0 <= i < max_count:
                            indices.add(i)
                except ValueError:
                    continue
            else:
                try:
                    i = self._normalize_index(int(token), one_based)
                    if 0 <= i < max_count:
                        indices.add(i)
                except ValueError:
                    continue
        return sorted(indices)

    def _should_use_one_based(self, s: str) -> bool:
        """默认使用 1 基索引，只有检测到历史 0 基输入时才回退兼容。"""
        for token in s.split(","):
            token = token.strip()
            if not token:
                continue
            if ("-" in token or ":" in token) and not token.startswith("-") and not token.startswith(":"):
                sep = "-" if "-" in token else ":"
                a, b = token.split(sep, 1)
                try:
                    if int(a) == 0 or int(b) == 0:
                        return False
                except ValueError:
                    continue
                continue
            try:
                if int(token) == 0:
                    return False
            except ValueError:
                continue
        return True

    @staticmethod
    def _normalize_index(value: int, one_based: bool) -> int:
        """把用户输入索引转换为内部 0 基索引。"""
        return value - 1 if one_based else value
