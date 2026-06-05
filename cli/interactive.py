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
        for i, item in enumerate(items):
            title = item.get("title", "未知") if isinstance(item, dict) else str(item)
            self.output.write(f"  [{i}] {title}\n")
        self.output.write("=" * 60 + "\n")
        self.output.write("请输入要下载的索引 (逗号分隔, 如 0,2,5) [a=全选/n=不选/q=取消]: ")
        self.output.flush()

    def _parse_index_list(self, s: str, max_count: int) -> list[int]:
        """解析逗号分隔的索引字符串，支持范围 (如 "0,2-5")。"""
        indices = set()
        for token in s.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token and not token.startswith("-"):
                a, b = token.split("-", 1)
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
