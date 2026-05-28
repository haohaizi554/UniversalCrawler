"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/error.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/error.py
try:
    from ..translation import _
except ImportError:
    """提供 `_` 对应的内部辅助逻辑。"""
    def _(x):
        """Fallback translator that returns the original text unchanged."""

        return x

class DownloaderError(Exception):
    """定义 `DownloaderError` 异常类型，用于表达特定失败场景。"""
    def __init__(
        self,
        message: str = "",
    ):
        """初始化当前实例并准备运行所需的状态，供 `DownloaderError` 使用。"""
        self.message = message or _("项目代码错误")
        super().__init__(self.message)

    def __str__(self):
        """提供 `__str__` 对应的内部辅助逻辑，供 `DownloaderError` 使用。"""
        return f"DownloaderError: {self.message}"


class CacheError(Exception):
    """定义 `CacheError` 异常类型，用于表达特定失败场景。"""
    def __init__(self, message: str):
        """初始化当前实例并准备运行所需的状态，供 `CacheError` 使用。"""
        super().__init__(message)
        self.message = message

    def __str__(self):
        """提供 `__str__` 对应的内部辅助逻辑，供 `CacheError` 使用。"""
        return self.message