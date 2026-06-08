"""cli.selection 各种二次选择策略测试。

测试维度：
- 单元测试：每种策略的边界条件
- 白盒测试：规则解析、范围语法（0,2-5/0,2:5）
- 黑盒测试：完整 select 调用
"""

import io
import sys
import unittest
from unittest.mock import patch


class RuleSelectionTests(unittest.TestCase):
    """RuleSelection 单测。"""

    def test_all_default(self):
        """默认无参数 → 全选。"""
        from cli.selection import RuleSelection
        rs = RuleSelection()
        items = [{"index": 0}, {"index": 1}, {"index": 2}]
        self.assertEqual(rs.select(items), [0, 1, 2])

    def test_all_explicit(self):
        """all_items=True → 全选。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(all_items=True)
        items = [{"index": 0}, {"index": 1}]
        self.assertEqual(rs.select(items), [0, 1])

    def test_first(self):
        """first=True → 只选第一个。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(first=True)
        items = [{"index": 0}, {"index": 1}, {"index": 2}]
        self.assertEqual(rs.select(items), [0])

    def test_last(self):
        """last=True → 只选最后一个。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(last=True)
        items = [{"index": 0}, {"index": 1}, {"index": 2}]
        self.assertEqual(rs.select(items), [2])

    def test_select_specific_indices(self):
        """select='0,2,5' → 选 0/2/5。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,2,5")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2, 5])

    def test_select_dash_range(self):
        """select='0,2-5' → 选 0,2,3,4,5。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,2-5")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2, 3, 4, 5])

    def test_select_colon_range(self):
        """select='0,2:5' → 选 0,2,3,4,5（冒号也是范围分隔符）。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,2:5")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2, 3, 4, 5])

    def test_select_out_of_range_filtered(self):
        """select='0,99' → 越界 99 被丢弃。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,99")
        items = [{"index": i} for i in range(3)]
        self.assertEqual(rs.select(items), [0])

    def test_select_negative_filtered(self):
        """select='0,-1' → 负数被丢弃。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,-1")
        items = [{"index": i} for i in range(3)]
        self.assertEqual(rs.select(items), [0])

    def test_exclude(self):
        """exclude='1,2' → 排除 1,2。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(exclude="1,2")
        items = [{"index": i} for i in range(5)]
        self.assertEqual(rs.select(items), [0, 3, 4])

    def test_exclude_with_select(self):
        """select='0,1,2,3' + exclude='2' → 选 0,1,3。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,1,2,3", exclude="2")
        items = [{"index": i} for i in range(5)]
        self.assertEqual(rs.select(items), [0, 1, 3])

    def test_first_with_exclude(self):
        """first + exclude='0' → 选 [0] 然后排除 0 → [空]。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(first=True, exclude="0")
        items = [{"index": 0}, {"index": 1}]
        self.assertEqual(rs.select(items), [])

    def test_empty_items(self):
        """空 items → 空列表（不能崩）。"""
        from cli.selection import RuleSelection
        rs = RuleSelection()
        self.assertEqual(rs.select([]), [])

    def test_select_with_whitespace(self):
        """select=' 0 , 2 , 5 ' → 容忍空白。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select=" 0 , 2 , 5 ")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2, 5])

    def test_select_with_empty_token(self):
        """select='0,,2' → 容忍空 token。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,,2")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2])

    def test_select_with_invalid_token_skipped(self):
        """select='0,abc,2' → 非法 token 跳过。"""
        from cli.selection import RuleSelection
        rs = RuleSelection(select="0,abc,2")
        items = [{"index": i} for i in range(6)]
        self.assertEqual(rs.select(items), [0, 2])

    def test_strategy_name(self):
        """strategy_name 必须返回 'rule'。"""
        from cli.selection import RuleSelection
        self.assertEqual(RuleSelection().strategy_name, "rule")


class SelectionSummaryHelpersTests(unittest.TestCase):
    """统一选择提示与摘要 helper 测试。"""

    def test_build_selection_prompt_uses_shared_format(self):
        """选择轮次和候选数应采用统一提示格式。"""
        from cli.selection_base import build_selection_prompt

        self.assertEqual(build_selection_prompt(2, 5), "二次选择 #2: 5 个候选")

    def test_format_selection_result_truncates_preview_when_needed(self):
        """选择结果摘要应截断过长预览，避免日志噪声。"""
        from cli.selection_base import format_selection_result

        rendered = format_selection_result(list(range(12)))

        self.assertIn("选中 12 项", rendered)
        self.assertIn("[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]", rendered)
        self.assertTrue(rendered.endswith("..."))


class AutoSelectionTests(unittest.TestCase):
    """AutoSelection 自动检测策略。"""

    def test_tty_picks_interactive(self):
        """stdin 是 TTY → 选 InteractiveTTYSelection。"""
        from cli.selection import AutoSelection
        # 注意：必须先 patch，再 __init__（检测在 __init__ 里）
        with patch("sys.stdin.isatty", return_value=True):
            auto = AutoSelection()
        self.assertEqual(auto.strategy_name, "interactive")

    def test_pipe_picks_pipe(self):
        """stdin 非 TTY（管道）→ 选 PipeSelection。"""
        from cli.selection import AutoSelection
        with patch("sys.stdin.isatty", return_value=False):
            auto = AutoSelection()
        self.assertEqual(auto.strategy_name, "pipe")

    def test_isatty_raises_falls_back_to_rule(self):
        """stdin.isatty() 抛异常 → 兜底 RuleSelection。"""
        from cli.selection import AutoSelection
        with patch("sys.stdin.isatty", side_effect=ValueError("broken")):
            auto = AutoSelection()
        # 兜底策略可以是 rule
        self.assertEqual(auto.strategy_name, "rule")

    def test_select_delegates(self):
        """AutoSelection.select 必须委托给选中的策略。"""
        from cli.selection import AutoSelection
        with patch("sys.stdin.isatty", return_value=False):
            auto = AutoSelection()
        # 用预加载的 PipeSelection 验证委托
        from cli.pipe import PipeSelection
        auto._strategy = PipeSelection(preloaded_choices=[[0, 2]])
        self.assertEqual(auto.select([{"i": 0}, {"i": 1}, {"i": 2}]), [0, 2])


class InteractiveTTYSelectionTests(unittest.TestCase):
    """TTY 交互选择的输入兼容性测试。"""

    def test_parse_one_based_indices(self):
        """面板展示从 1 开始时，输入 1,3 应映射到内部 0,2。"""
        from cli.interactive import InteractiveTTYSelection

        selection = InteractiveTTYSelection()
        self.assertEqual(selection._parse_index_list("1,3", 5), [0, 2])

    def test_parse_zero_based_indices_for_backward_compatibility(self):
        """历史 0 基输入仍然可用，避免破坏已有脚本。"""
        from cli.interactive import InteractiveTTYSelection

        selection = InteractiveTTYSelection()
        self.assertEqual(selection._parse_index_list("0,2", 5), [0, 2])

    def test_print_items_renders_group_title_once(self):
        """共享 group_title 时，只在顶部显示一次，不在每行重复父级标题。"""
        from cli.interactive import InteractiveTTYSelection

        output = io.StringIO()
        selection = InteractiveTTYSelection(input_stream=io.StringIO("q\n"), output_stream=output)
        items = [
            {"title": "我的空乘女友", "subtitle": "P01", "group_title": "sunny77小合集"},
            {"title": "我的好利来女友 第二期", "subtitle": "P02", "group_title": "sunny77小合集"},
        ]

        selection._print_items(items, "二次选择 #1: 2 个候选")

        rendered = output.getvalue()
        self.assertIn("📦 当前分组: sunny77小合集", rendered)
        self.assertEqual(rendered.count("sunny77小合集"), 1)
        self.assertIn("[1] 我的空乘女友", rendered)
        self.assertIn("P01", rendered)


if __name__ == "__main__":
    unittest.main()
