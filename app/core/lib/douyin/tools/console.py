"""提供适合 PyQt6 QThread 调用的轻量控制台输出接口。"""

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
    # 独立加载时提供与 Rich 样式参数兼容的默认值。
    PROMPT = "bold cyan"
    GENERAL = "bold white"
    INFO = "bold green"
    WARNING = "bold yellow"
    ERROR = "bold red"
    DEBUG = "bold magenta"

__all__ = ["ColorfulConsole"]

class ColorfulConsole:
    """保持 Rich 风格的调用签名，但不继承 rich.Console。

    该限制用于避免与 PyQt6 QThread 组合时触发 0xC0000409 崩溃。
    """

    def __init__(self, *args, debug: bool = False, **kwargs):
        self.debug_mode = debug

    def print(self, *args, style=GENERAL, highlight=False, **kwargs):
        # 接受 Rich 的样式参数，但输出保持为纯文本。
        msg = " ".join(str(a) for a in args)
        print(msg)

    def info(self, *args, highlight=False, **kwargs):
        self.print(*args, **kwargs)

    def warning(self, *args, highlight=False, **kwargs):
        self.print(*args, **kwargs)

    def error(self, *args, highlight=False, **kwargs):
        self.print(*args, **kwargs)

    def debug(self, *args, highlight=False, **kwargs):
        if self.debug_mode:
            self.print(*args, **kwargs)

    def input(self, prompt="", style=PROMPT, *args, **kwargs):
        try:
            return input(prompt)
        except EOFError as e:
            raise e
