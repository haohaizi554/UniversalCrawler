"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/cleaner.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/cleaner.py
from platform import system
from re import compile
from string import whitespace
from emoji import replace_emoji
try:
    from ..translation import _
except ImportError:
    """提供 `_` 对应的内部辅助逻辑。"""
    def _(x):
        """Fallback translator that returns the original text unchanged."""

        return x
__all__ = ["Cleaner"]

class Cleaner:
    """封装 `Cleaner` 在 `app/core/lib/douyin/tools/cleaner.py` 中承担的核心逻辑。"""
    CONTROL_CHARACTERS = compile(r"[\x00-\x1F\x7F]")
    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `Cleaner` 使用。"""
        self.rule = self.default_rule()  # 默认非法字符字典
    @staticmethod
    def default_rule():
        """根据系统类型生成默认非法字符字典"""
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
            }  # Windows 系统和 Mac 系统
        elif s == "Linux":
            rule = {
                "/": "",
                "\x00": "",
            }  # Linux 系统
        else:
            print(_("不受支持的操作系统类型，可能无法正常去除非法字符！"))
            rule = {}
        cache = {i: "" for i in whitespace[1:]}  # 补充换行符等非法字符
        return rule | cache
    def set_rule(self, rule: dict[str, str], update=False):
        """设置 `rule` 对应的值或运行状态，供 `Cleaner` 使用。"""
        self.rule = {**self.rule, **rule} if update else rule
    def filter(self, text: str) -> str:
        """执行 `filter` 对应的业务逻辑，供 `Cleaner` 使用。"""
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
        """执行 `clear_spaces` 对应的业务逻辑，供 `Cleaner` 使用。"""
        return " ".join(string.split())
    @classmethod
    def remove_control_characters(
        cls,
        text,
        replace="",
    ):
        # 使用正则表达式匹配所有控制字符
        """执行 `remove_control_characters` 对应的业务逻辑，供 `Cleaner` 使用。"""
        return cls.CONTROL_CHARACTERS.sub(
            replace,
            text,
        )

if __name__ == "__main__":
    demo = Cleaner()
    print(demo.rule)
    print(demo.filter_name(""))
    print(demo.remove_control_characters("hello \x08world"))