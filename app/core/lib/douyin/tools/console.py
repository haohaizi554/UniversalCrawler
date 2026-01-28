from rich.console import Console
from rich.text import Text
# 尝试导入自定义常量，如果失败则使用默认值
# 这里的 src.custom 应该被替换为当前包的引用
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

class ColorfulConsole(Console):
    def __init__(self, *args, debug: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug_mode = debug

    def print(self, *args, style=GENERAL, highlight=False, **kwargs):
        super().print(*args, style=style, highlight=highlight, **kwargs)

    def info(self, *args, highlight=False, **kwargs):
        self.print(*args, style=INFO, highlight=highlight, **kwargs)

    def warning(self, *args, highlight=False, **kwargs):
        self.print(*args, style=WARNING, highlight=highlight, **kwargs)

    def error(self, *args, highlight=False, **kwargs):
        self.print(*args, style=ERROR, highlight=highlight, **kwargs)

    def debug(self, *args, highlight=False, **kwargs):
        if self.debug_mode:
            self.print(*args, style=DEBUG, highlight=highlight, **kwargs)

    def input(self, prompt="", style=PROMPT, *args, **kwargs):
        try:
            return super().input(Text(prompt, style=style), *args, **kwargs)
        except EOFError as e:
            raise KeyboardInterrupt from e