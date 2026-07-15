"""定义下载流程与缓存迁移使用的领域异常。"""

try:
    from ..translation import _
except ImportError:
    def _(x):

        return x

class DownloaderError(Exception):
    """表示下载器内部状态或响应类型不符合预期。"""
    def __init__(
        self,
        message: str = "",
    ):
        self.message = message or _("项目代码错误")
        super().__init__(self.message)

    def __str__(self):
        return f"DownloaderError: {self.message}"

class CacheError(Exception):
    """表示旧缓存目录迁移失败。"""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message
