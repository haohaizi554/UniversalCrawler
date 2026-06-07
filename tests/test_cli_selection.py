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


if __name__ == "__main__":
    unittest.main()
