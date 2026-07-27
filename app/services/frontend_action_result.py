"""前端动作处理的统一结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FrontendActionResult:
    """将服务层动作结果稳定地投影为 GUI 与 WebUI 都可消费的数据。"""

    status: str
    message: str = ""
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"status": self.status}
        if self.message:
            result["message"] = self.message
        if self.data:
            result["data"] = self.data
        return result
