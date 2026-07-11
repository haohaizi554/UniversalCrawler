"""stdin/stdout 管道选择模块。

从 stdin 读取 JSON 列表决定选择，或向 stdout 写入 JSON 格式的进度/结果。
支持多种输入格式：
- `[0, 2, 5]` 直接给索引列表
- `{"indices": [0, 2, 5]}` 索引字典
- `{"items": [{"selected": true, "index": 0}, ...]}` 详细模式

同时支持向 stdout 写入结构化输出（用于管道传递给其他程序）。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cli.selection_base import SelectionStrategy

class PipeSelection(SelectionStrategy):
    """stdin 管道选择策略。

    从 stdin 读 JSON 列表决定选择。
    支持预加载多次选择（用于合集场景的多次 ask_user_selection）。

    Attributes:
        input_stream: 输入流（默认 sys.stdin）
        output_stream: 输出流（默认 None，不输出）
        preloaded_choices: 预设的多轮选择 (用于批量处理多次 ask_user_selection)
    """

    def __init__(
        self,
        input_stream=None,
        output_stream=None,
        preloaded_choices: list[list[int]] | None = None,
    ):
        """初始化管道选择策略。

        Args:
            input_stream: stdin 流（默认 sys.stdin）
            output_stream: stdout 流（默认 None）
            preloaded_choices: 预加载的多轮选择 [[0,1,2], [3,4], []]。
                              用于合集场景：spider 多次调用 ask_user_selection 时，
                              预先准备好每一轮的答案。
        """
        self.input = input_stream or sys.stdin
        self.output = output_stream
        self._preloaded = preloaded_choices
        self._call_count = 0

    @property
    def strategy_name(self) -> str:
        return "pipe"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        """从 stdin 或预加载中选择。"""
        n = len(items)

        # 优先使用预加载的选择 (用于合集场景)
        if self._preloaded is not None:
            return self._select_from_preloaded(n)

        # 从 stdin 读 JSON
        self._print_prompt_to_stderr(prompt)
        return self._read_from_stdin(n)

    def _select_from_preloaded(self, n: int) -> list[int]:
        """从预加载的答案中选择。"""
        preloaded = self._preloaded or []
        if self._call_count < len(preloaded):
            indices = preloaded[self._call_count]
            self._call_count += 1
            return [i for i in indices if 0 <= i < n]
        else:
            # 超出预加载数量 → 默认全选
            return list(range(n))

    def _read_from_stdin(self, n: int) -> list[int] | None:
        """从 stdin 读取选择。"""
        try:
            line = self.input.readline()
        except (EOFError, KeyboardInterrupt):
            return None

        if not line:
            return None

        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        return self._parse_json_data(data, n)

    def _parse_json_data(self, data: Any, n: int) -> list[int] | None:
        """解析 JSON 数据为索引列表。"""
        def _coerce_index(value: Any) -> int | None:
            try:
                index = int(value)
            except (TypeError, ValueError):
                return None
            return index if 0 <= index < n else None

        # 格式 1: `[0, 2, 5]`
        if isinstance(data, list):
            indices = [_coerce_index(value) for value in data]
            return [index for index in indices if index is not None]

        # 格式 2: `{"indices": [0, 2, 5]}`
        if isinstance(data, dict):
            if "indices" in data:
                indices = [_coerce_index(value) for value in data["indices"]]
                return [index for index in indices if index is not None]
            if "selected" in data and isinstance(data["selected"], list):
                indices = [_coerce_index(value) for value in data["selected"]]
                return [index for index in indices if index is not None]
            if "items" in data and isinstance(data["items"], list):
                selected_indices: list[int] = []
                for j, it in enumerate(data["items"]):
                    if isinstance(it, dict) and it.get("selected", True):
                        index = _coerce_index(it.get("index", j))
                        if index is not None:
                            selected_indices.append(index)
                return selected_indices

        return None

    def _print_prompt_to_stderr(self, prompt: str) -> None:
        """向 stderr 打印提示信息。"""
        msg = {
            "type": "select_tasks",
            "count": len(prompt) if prompt else 0,
            "prompt": prompt,
        }
        sys.stderr.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stderr.flush()

class PipeOutput:
    """结构化输出器：向 stdout 写入 JSON 格式的进度和结果。

    用于将爬虫进度/结果通过管道传递给其他程序。
    """

    def __init__(self, output_stream=None):
        self.output = output_stream or sys.stdout
        self._started = False

    def start(self, source: str, keyword: str, total: int | None = None) -> None:
        """开始输出。"""
        self._write({
            "type": "start",
            "source": source,
            "keyword": keyword,
            "total": total,
        })
        self._started = True

    def item_found(self, item: dict) -> None:
        """发现新项目。"""
        self._write({
            "type": "item_found",
            "item": item,
        })

    def selection_required(self, items: list, prompt: str) -> None:
        """需要用户选择。"""
        self._write({
            "type": "selection_required",
            "items": items,
            "prompt": prompt,
        })

    def download_start(self, video_id: str) -> None:
        """下载开始。"""
        self._write({
            "type": "download_start",
            "video_id": video_id,
        })

    def download_progress(self, video_id: str, progress: int) -> None:
        """下载进度。"""
        self._write({
            "type": "download_progress",
            "video_id": video_id,
            "progress": progress,
        })

    def download_finish(self, video_id: str, local_path: str) -> None:
        """下载完成。"""
        self._write({
            "type": "download_finish",
            "video_id": video_id,
            "local_path": local_path,
        })

    def download_error(self, video_id: str, error: str) -> None:
        """下载错误。"""
        self._write({
            "type": "download_error",
            "video_id": video_id,
            "error": error,
        })

    def finish(self, items: list, elapsed: float) -> None:
        """全部完成。"""
        self._write({
            "type": "finish",
            "items": items,
            "elapsed": elapsed,
        })
        self._started = False

    def _write(self, data: dict) -> None:
        """写入 JSON 数据。"""
        self.output.write(json.dumps(data, ensure_ascii=False) + "\n")
        self.output.flush()
