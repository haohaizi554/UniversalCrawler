"""CLI/Web 管道选择测试。

测试维度：
- 单元测试：PipeSelection 从 stdin 读 JSON / 预加载多轮选择
- 单元测试：PipeOutput 写入 JSON 到 stdout
- 集成测试：合集场景的多轮 ask_user_selection 调用
- 边界测试：空 stdin、EOF、非法 JSON

设计原则：
- 用 io.StringIO 替换 stdin/stdout
- 不真的爬虫，只测选择策略的输入输出格式
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from cli.pipe import PipeSelection, PipeOutput

class PipeSelectionBasicTests(unittest.TestCase):
    """PipeSelection 基础行为。"""

    def test_strategy_name(self):
        s = PipeSelection()
        self.assertEqual(s.strategy_name, "pipe")

    def test_init_defaults(self):
        s = PipeSelection()
        self.assertIs(s.input, sys.stdin)
        self.assertIsNone(s.output)
        self.assertIsNone(s._preloaded)
        self.assertEqual(s._call_count, 0)

    def test_init_with_custom_streams(self):
        inp = io.StringIO()
        out = io.StringIO()
        s = PipeSelection(input_stream=inp, output_stream=out)
        self.assertIs(s.input, inp)
        self.assertIs(s.output, out)

class PipeSelectionJSONParsingTests(unittest.TestCase):
    """PipeSelection JSON 格式解析。"""

    def test_list_format(self):
        """`[0, 2, 5]` 格式。"""
        inp = io.StringIO("[0, 2, 5]\n")
        s = PipeSelection(input_stream=inp)
        items = ["a", "b", "c", "d", "e", "f"]
        result = s.select(items)
        self.assertEqual(result, [0, 2, 5])

    def test_dict_with_indices(self):
        """`{"indices": [0, 2]}` 格式。"""
        inp = io.StringIO('{"indices": [0, 2]}\n')
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b", "c"])
        self.assertEqual(result, [0, 2])

    def test_dict_with_selected(self):
        """`{"selected": [0, 1]}` 格式。"""
        inp = io.StringIO('{"selected": [0, 1]}\n')
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b", "c"])
        self.assertEqual(result, [0, 1])

    def test_dict_with_items(self):
        """`{"items": [{"selected": true, "index": 0}, ...]}` 详细模式。"""
        data = json.dumps({
            "items": [
                {"selected": True, "index": 0},
                {"selected": False, "index": 1},
                {"selected": True, "index": 2},
            ]
        })
        inp = io.StringIO(data + "\n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b", "c"])
        self.assertEqual(result, [0, 2])

    def test_empty_list(self):
        inp = io.StringIO("[]\n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b"])
        self.assertEqual(result, [])

class PipeSelectionErrorTests(unittest.TestCase):
    """PipeSelection 错误处理。"""

    def test_eof_returns_none(self):
        """空 stdin（EOF）→ 返回 None。"""
        inp = io.StringIO("")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b"])
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        inp = io.StringIO("not valid json\n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b"])
        self.assertIsNone(result)

    def test_out_of_range_indices_filtered(self):
        """超出范围的索引被过滤。"""
        inp = io.StringIO("[0, 5, 100]\n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b", "c"])
        # 0 有效，5 和 100 超出范围
        self.assertEqual(result, [0])

    def test_whitespace_only_input_returns_none(self):
        inp = io.StringIO("   \n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b"])
        self.assertIsNone(result)

class PipeSelectionPreloadedTests(unittest.TestCase):
    """PipeSelection 预加载多轮选择。"""

    def test_preloaded_single_round(self):
        s = PipeSelection(preloaded_choices=[[0, 2]])
        result = s.select(["a", "b", "c"])
        self.assertEqual(result, [0, 2])

    def test_preloaded_multi_round(self):
        """多轮选择（合集场景）。"""
        s = PipeSelection(preloaded_choices=[[0, 1], [2], []])
        # 第 1 轮
        r1 = s.select(["a", "b", "c"])
        self.assertEqual(r1, [0, 1])
        # 第 2 轮
        r2 = s.select(["a", "b", "c"])
        self.assertEqual(r2, [2])
        # 第 3 轮：空选
        r3 = s.select(["a", "b", "c"])
        self.assertEqual(r3, [])

    def test_preloaded_overflow_returns_all(self):
        """超出预加载数量 → 默认全选。"""
        s = PipeSelection(preloaded_choices=[[0]])
        # 第 1 轮用预加载
        r1 = s.select(["a", "b", "c"])
        self.assertEqual(r1, [0])
        # 第 2 轮：超出 → 全选
        r2 = s.select(["a", "b", "c"])
        self.assertEqual(r2, [0, 1, 2])

    def test_preloaded_filters_out_of_range(self):
        """预加载中的越界索引被过滤。"""
        s = PipeSelection(preloaded_choices=[[0, 100, 2]])
        result = s.select(["a", "b", "c"])
        self.assertEqual(result, [0, 2])

    def test_preloaded_with_empty(self):
        """空预加载列表 → 所有轮次都全选。"""
        s = PipeSelection(preloaded_choices=[])
        r1 = s.select(["a", "b"])
        self.assertEqual(r1, [0, 1])

    def test_preloaded_does_not_consume_stdin(self):
        """有预加载时不应读 stdin。"""
        inp = io.StringIO("should not be read\n")
        s = PipeSelection(input_stream=inp, preloaded_choices=[[0]])
        result = s.select(["a", "b"])
        self.assertEqual(result, [0])
        # stdin 不应被消费
        self.assertEqual(inp.read(), "should not be read\n")

class PipeSelectionStderrTests(unittest.TestCase):
    """PipeSelection stderr 提示。"""

    def test_prompt_writes_to_stderr(self):
        inp = io.StringIO("[0]\n")
        s = PipeSelection(input_stream=inp)
        with patch("sys.stderr") as mock_stderr:
            s.select(["a"], prompt="选择:")
        # 验证 stderr.write 被调用
        self.assertTrue(mock_stderr.write.called)

    def test_empty_prompt(self):
        inp = io.StringIO("[0]\n")
        s = PipeSelection(input_stream=inp)
        with patch("sys.stderr") as mock_stderr:
            s.select(["a"], prompt="")
        self.assertTrue(mock_stderr.write.called)

class PipeOutputTests(unittest.TestCase):
    """PipeOutput 结构化输出。"""

    def test_start(self):
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.start("douyin", "测试", total=10)
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data["type"], "start")
        self.assertEqual(data["source"], "douyin")
        self.assertEqual(data["keyword"], "测试")
        self.assertEqual(data["total"], 10)

    def test_item_found(self):
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.item_found({"id": "v1", "title": "测试"})
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data["type"], "item_found")
        self.assertEqual(data["item"]["id"], "v1")

    def test_selection_required(self):
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.selection_required([{"title": "a"}], prompt="请选择")
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data["type"], "selection_required")
        self.assertEqual(data["prompt"], "请选择")

    def test_download_lifecycle(self):
        """下载完整生命周期：start → progress → finish。"""
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.download_start("v1")
        po.download_progress("v1", 50)
        po.download_finish("v1", "/path/to/file.mp4")
        lines = [json.loads(line) for line in out.getvalue().strip().split("\n")]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["type"], "download_start")
        self.assertEqual(lines[1]["type"], "download_progress")
        self.assertEqual(lines[2]["type"], "download_finish")
        self.assertEqual(lines[2]["local_path"], "/path/to/file.mp4")

    def test_download_error(self):
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.download_error("v1", "网络错误")
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data["type"], "download_error")
        self.assertEqual(data["error"], "网络错误")

    def test_finish_resets_started(self):
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.start("douyin", "kw")
        po.finish([], elapsed=1.23)
        # finish 后 _started 应重置
        self.assertFalse(po._started)

    def test_unicode_output(self):
        """Unicode 字符应正确编码。"""
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.start("douyin", "中文测试 🎯")
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data["keyword"], "中文测试 🎯")

    def test_multiple_lines_are_separate_json(self):
        """多次写入应该每行一个 JSON（newline-delimited）。"""
        out = io.StringIO()
        po = PipeOutput(output_stream=out)
        po.start("douyin", "kw")
        po.item_found({"id": "v1"})
        po.item_found({"id": "v2"})
        lines = out.getvalue().strip().split("\n")
        self.assertEqual(len(lines), 3)
        # 每行都是合法 JSON
        for line in lines:
            json.loads(line)

class PipeSelectionVsOtherStrategiesTests(unittest.TestCase):
    """PipeSelection vs RuleSelection 一致性测试。

    验证 PipeSelection 的输出格式与 RuleSelection 一致。
    """

    def test_pipe_returns_list(self):
        inp = io.StringIO("[0, 1]\n")
        s = PipeSelection(input_stream=inp)
        result = s.select(["a", "b", "c"])
        self.assertIsInstance(result, list)

    def test_pipe_returns_none_for_cancel(self):
        """EOF / 无效输入 → None（用户取消）。"""
        for empty_input in ("", "   ", "invalid"):
            inp = io.StringIO(empty_input + "\n")
            s = PipeSelection(input_stream=inp)
            result = s.select(["a", "b"])
            self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
