"""cli.pipe PipeSelection 单元测试（管道选择 + 预加载 + 输出）。

测试维度：
- 单元测试：stdin 读取、JSON 解析
- 黑盒测试：合集场景多次 ask_user_selection
- 管道测试：output_stream 写入 JSON
"""

import io
import json
import unittest
from unittest.mock import patch

class PipeSelectionPreloadTests(unittest.TestCase):
    """预加载多轮选择测试（合集场景）。"""

    def test_preload_one_round(self):
        """预加载 [[0, 1, 2]] → 第一轮返回 [0, 1, 2]。"""
        from cli.pipe import PipeSelection
        ps = PipeSelection(preloaded_choices=[[0, 1, 2]])
        items = [{"i": 0}, {"i": 1}, {"i": 2}, {"i": 3}]
        self.assertEqual(ps.select(items), [0, 1, 2])

    def test_preload_two_rounds(self):
        """预加载 [[0], [1, 2]] → 第一次 0, 第二次 1,2。"""
        from cli.pipe import PipeSelection
        ps = PipeSelection(preloaded_choices=[[0], [1, 2]])
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        # 第一次
        self.assertEqual(ps.select(items), [0])
        # 第二次
        self.assertEqual(ps.select(items), [1, 2])

    def test_preload_exhausted_defaults_to_all(self):
        """预加载用完后 → 默认全选。"""
        from cli.pipe import PipeSelection
        ps = PipeSelection(preloaded_choices=[[0]])
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        ps.select(items)  # 消耗 [0]
        # 第二次：预加载用完 → 全选
        self.assertEqual(ps.select(items), [0, 1, 2])

    def test_preload_out_of_range_filtered(self):
        """预加载里的越界索引被过滤。"""
        from cli.pipe import PipeSelection
        ps = PipeSelection(preloaded_choices=[[0, 99, 2]])
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        self.assertEqual(ps.select(items), [0, 2])

    def test_preload_empty_choice(self):
        """预加载 []（空选）→ 返回 []。"""
        from cli.pipe import PipeSelection
        ps = PipeSelection(preloaded_choices=[[]])
        items = [{"i": 0}, {"i": 1}]
        self.assertEqual(ps.select(items), [])

    def test_preload_helper_without_rounds_defaults_to_all(self):
        """即使内部辅助方法被复用，也不应对空预加载值解引用。"""
        from cli.pipe import PipeSelection

        ps = PipeSelection(preloaded_choices=None)

        self.assertEqual(ps._select_from_preloaded(3), [0, 1, 2])

class PipeSelectionStdinTests(unittest.TestCase):
    """从 stdin 读取 JSON 测试。"""

    def test_stdin_reads_list_format(self):
        """stdin 喂 '[0, 2, 5]' → 选 0,2,5。"""
        from cli.pipe import PipeSelection
        stdin = io.StringIO("[0, 2, 5]\n")
        ps = PipeSelection(input_stream=stdin)
        items = [{"i": i} for i in range(6)]
        self.assertEqual(ps.select(items), [0, 2, 5])

    def test_stdin_ignores_invalid_indices_in_mixed_list(self):
        from cli.pipe import PipeSelection

        stdin = io.StringIO('[0, "bad", null, 2]\n')
        ps = PipeSelection(input_stream=stdin)

        self.assertEqual(ps.select([{"i": i} for i in range(3)]), [0, 2])

    def test_stdin_reads_dict_format(self):
        """stdin 喂 '{\"indices\": [0, 2]}' → 选 0,2。"""
        from cli.pipe import PipeSelection
        stdin = io.StringIO('{"indices": [0, 2]}\n')
        ps = PipeSelection(input_stream=stdin)
        items = [{"i": i} for i in range(3)]
        self.assertEqual(ps.select(items), [0, 2])

    def test_stdin_reads_detailed_format(self):
        """stdin 喂 '{\"items\": [{\"selected\": true, \"index\": 0}, ...]}' → 选 selected=true 的。"""
        from cli.pipe import PipeSelection
        stdin = io.StringIO(
            '{"items": [{"selected": true, "index": 0}, {"selected": false, "index": 1}, {"selected": true, "index": 2}]}\n'
        )
        ps = PipeSelection(input_stream=stdin)
        items = [{"i": 0}, {"i": 1}, {"i": 2}]
        self.assertEqual(ps.select(items), [0, 2])

    def test_stdin_eof_returns_none(self):
        """stdin EOF → 返回 None（用户取消语义）。"""
        from cli.pipe import PipeSelection
        stdin = io.StringIO("")  # 空 → EOF
        ps = PipeSelection(input_stream=stdin)
        items = [{"i": 0}, {"i": 1}]
        self.assertIsNone(ps.select(items))

    def test_stdin_invalid_json_returns_none(self):
        """stdin 非法 JSON → 返回 None。"""
        from cli.pipe import PipeSelection
        stdin = io.StringIO("not valid json\n")
        ps = PipeSelection(input_stream=stdin)
        items = [{"i": 0}, {"i": 1}]
        self.assertIsNone(ps.select(items))

class PipeSelectionOutputTests(unittest.TestCase):
    """PipeSelection prompt 输出到 stderr（用于管道消费）。"""

    def test_prompt_written_to_stderr(self):
        """prompt 必须写入 stderr。"""
        from cli.pipe import PipeSelection
        stderr_capture = io.StringIO()
        ps = PipeSelection(input_stream=io.StringIO(""), output_stream=None)
        items = [{"title": f"item-{i}", "index": i} for i in range(3)]
        with patch("sys.stderr", stderr_capture):
            ps.select(items, prompt="请选择:")
        # stderr 应该有 prompt 输出
        self.assertGreater(len(stderr_capture.getvalue()), 0)

    def test_prompt_format_is_json(self):
        """prompt 输出必须是合法 JSON。"""
        from cli.pipe import PipeSelection
        stderr_capture = io.StringIO()
        ps = PipeSelection(input_stream=io.StringIO(""))
        items = [{"title": "test", "index": 0}]
        with patch("sys.stderr", stderr_capture):
            ps.select(items, prompt="请选择:")
        # stderr 第一行是 JSON
        first_line = stderr_capture.getvalue().strip().split("\n")[0]
        try:
            data = json.loads(first_line)
            self.assertIn("type", data)
            self.assertEqual(data["type"], "select_tasks")
            self.assertIn("prompt", data)
        except json.JSONDecodeError:
            self.fail(f"prompt output is not valid JSON: {first_line}")

if __name__ == "__main__":
    unittest.main()
