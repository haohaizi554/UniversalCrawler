"""Host-neutral pipe selection helpers."""

from __future__ import annotations

import json
import sys
from typing import Any

from shared.selection_runtime import SelectionStrategy

class PipeSelection(SelectionStrategy):
    """stdin 管道选择策略。"""

    def __init__(
        self,
        input_stream=None,
        output_stream=None,
        preloaded_choices: list[list[int]] | None = None,
    ):
        self.input = input_stream or sys.stdin
        self.output = output_stream
        self._preloaded = preloaded_choices
        self._call_count = 0

    @property
    def strategy_name(self) -> str:
        return "pipe"

    def select(self, items: list, prompt: str = "") -> list[int] | None:
        n = len(items)
        if self._preloaded is not None:
            return self._select_from_preloaded(n)
        self._print_prompt_to_stderr(prompt)
        return self._read_from_stdin(n)

    def _select_from_preloaded(self, n: int) -> list[int]:
        preloaded = self._preloaded or []
        if self._call_count < len(preloaded):
            indices = preloaded[self._call_count]
            self._call_count += 1
            return [i for i in indices if 0 <= i < n]
        return list(range(n))

    def _read_from_stdin(self, n: int) -> list[int] | None:
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
        def _coerce_index(value: Any) -> int | None:
            try:
                index = int(value)
            except (TypeError, ValueError):
                return None
            return index if 0 <= index < n else None

        if isinstance(data, list):
            indices = [_coerce_index(i) for i in data]
            return [index for index in indices if index is not None]

        if isinstance(data, dict):
            if "indices" in data:
                indices = [_coerce_index(i) for i in data["indices"]]
                return [index for index in indices if index is not None]
            if "selected" in data and isinstance(data["selected"], list):
                indices = [_coerce_index(i) for i in data["selected"]]
                return [index for index in indices if index is not None]
            if "items" in data and isinstance(data["items"], list):
                selected_indices: list[int] = []
                for j, it in enumerate(data["items"]):
                    if isinstance(it, dict) and it.get("selected", True):
                        idx = _coerce_index(it.get("index", j))
                        if idx is not None:
                            selected_indices.append(idx)
                return selected_indices

        return None

    def _print_prompt_to_stderr(self, prompt: str) -> None:
        msg = {
            "type": "select_tasks",
            "count": len(prompt) if prompt else 0,
            "prompt": prompt,
        }
        sys.stderr.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stderr.flush()

class PipeOutput:
    """结构化输出器：向 stdout 写入 JSON 格式的进度和结果。"""

    def __init__(self, output_stream=None):
        self.output = output_stream or sys.stdout
        self._started = False

    def start(self, source: str, keyword: str, total: int | None = None) -> None:
        self._write({
            "type": "start",
            "source": source,
            "keyword": keyword,
            "total": total,
        })
        self._started = True

    def item_found(self, item: dict) -> None:
        self._write({
            "type": "item_found",
            "item": item,
        })

    def selection_required(self, items: list, prompt: str) -> None:
        self._write({
            "type": "selection_required",
            "items": items,
            "prompt": prompt,
        })

    def download_start(self, video_id: str) -> None:
        self._write({
            "type": "download_start",
            "video_id": video_id,
        })

    def download_progress(self, video_id: str, progress: int) -> None:
        self._write({
            "type": "download_progress",
            "video_id": video_id,
            "progress": progress,
        })

    def download_finish(self, video_id: str, local_path: str) -> None:
        self._write({
            "type": "download_finish",
            "video_id": video_id,
            "local_path": local_path,
        })

    def download_error(self, video_id: str, error: str) -> None:
        self._write({
            "type": "download_error",
            "video_id": video_id,
            "error": error,
        })

    def finish(self, items: list, elapsed: float) -> None:
        self._write({
            "type": "finish",
            "items": items,
            "elapsed": elapsed,
        })
        self._started = False

    def _write(self, data: dict) -> None:
        self.output.write(json.dumps(data, ensure_ascii=False) + "\n")
        self.output.flush()
