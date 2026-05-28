"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/console.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/console.py
# 修复：移除 rich.Console 继承，防止与 PyQt6 QThread 冲突导致 0xC0000409 栈溢出

# 尝试导入自定义常量，如果失败则使用默认值
try:
    from . import (
        PROMPT,
        GENERAL,
        INFO,
        WARNING,
        ERROR,
        DEBUG,
    )
except ImportError:
    # 默认颜色样式，确保独立运行时不报错
    PROMPT = "bold cyan"
    GENERAL = "bold white"
    INFO = "bold green"
    WARNING = "bold yellow"
    ERROR = "bold red"
    DEBUG = "bold magenta"

__all__ = ["ColorfulConsole"]


class ColorfulConsole:
    """
    简化的控制台类，不继承 rich.Console
    避免与 PyQt6 QThread 一起使用时导致 0xC0000409 栈溢出崩溃
    """

    def __init__(self, *args, debug: bool = False, **kwargs):
        """初始化当前实例并准备运行所需的状态，供 `ColorfulConsole` 使用。"""
        self.debug_mode = debug

    def print(self, *args, style=GENERAL, highlight=False, **kwargs):
        # 简化实现，直接打印
        """执行 `print` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        msg = " ".join(str(a) for a in args)
        print(msg)

    def info(self, *args, highlight=False, **kwargs):
        """执行 `info` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        self.print(*args, **kwargs)

    def warning(self, *args, highlight=False, **kwargs):
        """执行 `warning` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        self.print(*args, **kwargs)

    def error(self, *args, highlight=False, **kwargs):
        """执行 `error` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        self.print(*args, **kwargs)

    def debug(self, *args, highlight=False, **kwargs):
        """执行 `debug` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        if self.debug_mode:
            self.print(*args, **kwargs)

    def input(self, prompt="", style=PROMPT, *args, **kwargs):
        """执行 `input` 对应的业务逻辑，供 `ColorfulConsole` 使用。"""
        try:
            return input(prompt)
        except EOFError as e:
            raise e
