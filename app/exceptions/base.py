"""定义可携带错误码、严重级别和恢复策略的应用基础异常。"""

class AppError(Exception):
    """应用基础异常，支持结构化元数据用于恢复和日志。"""

    def __init__(self, message: str = "", *, code: str = "", severity: str = "error", recoverable: bool = False):
        super().__init__(message)
        self.message = message
        self.code = code
        self.severity = severity
        self.recoverable = recoverable

    def to_dict(self) -> dict:
        """序列化为字典，用于日志和 API 响应。"""
        return {
            "message": self.message,
            "code": self.code,
            "severity": self.severity,
            "recoverable": self.recoverable,
        }
