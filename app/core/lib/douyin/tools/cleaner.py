"""按操作系统规则清理文件名中的非法字符、控制符和表情。"""

from platform import system
from re import compile
from string import whitespace
from emoji import replace_emoji
try:
    from ..translation import _
except ImportError:
    def _(x):

        return x
__all__ = ["Cleaner"]

class Cleaner:
    """生成当前系统适用的文件名清理规则。"""

    CONTROL_CHARACTERS = compile(r"[\x00-\x1F\x7F]")
    def __init__(self):
        self.rule = self.default_rule()
    @staticmethod
    def default_rule():
        """返回当前系统不能出现在文件名中的字符替换表。"""
        if (s := system()) in ("Windows", "Darwin"):
            rule = {
                "/": "",
                "\\": "",
                "|": "",
                "<": "",
                ">": "",
                '"': "",
                "?": "",
                ":": "",
                "*": "",
                "\x00": "",
            }
        elif s == "Linux":
            rule = {
                "/": "",
                "\x00": "",
            }
        else:
            print(_("不受支持的操作系统类型，可能无法正常去除非法字符！"))
            rule = {}
        # 文件名中的换行和制表符同样会破坏后续路径处理。
        cache = {i: "" for i in whitespace[1:]}
        return rule | cache
    def set_rule(self, rule: dict[str, str], update=False):
        """替换规则表，或在 update=True 时合并到现有规则。"""
        self.rule = {**self.rule, **rule} if update else rule
    def filter(self, text: str) -> str:
        for i in self.rule:
            text = text.replace(i, self.rule[i])
        return text
    def filter_name(
        self,
        text: str,
        default: str = "",
    ) -> str:
        """过滤文件夹名称中的非法字符"""
        text = text.replace(":", ".")
        text = self.remove_control_characters(text)
        text = self.filter(text)
        text = replace_emoji(text)
        text = self.clear_spaces(text)
        text = text.strip().strip(".")
        return text or default

    @staticmethod
    def clear_spaces(string: str):
        return " ".join(string.split())
    @classmethod
    def remove_control_characters(
        cls,
        text,
        replace="",
    ):
        return cls.CONTROL_CHARACTERS.sub(
            replace,
            text,
        )

if __name__ == "__main__":
    demo = Cleaner()
    print(demo.rule)
    print(demo.filter_name(""))
    print(demo.remove_control_characters("hello \x08world"))
