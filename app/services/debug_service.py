"""服务模块，负责 `app/services/debug_service.py` 对应的业务支撑能力。"""

import os
import subprocess
from pathlib import Path

from app.debug_logger import debug_logger
from app.exceptions import DebugActionError

#调试产物管理服务
class DebugArtifactsService:
    """负责打开调试产物和复制 trace_id。"""

    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `DebugArtifactsService` 使用。"""
        self.logs_dir = debug_logger.logs_dir

    def latest_log_path(self) -> str:
        """执行 `latest_log_path` 对应的业务逻辑，供 `DebugArtifactsService` 使用。"""
        return str(debug_logger.latest_file)

    def latest_error_summary_path(self) -> str:
        """执行 `latest_error_summary_path` 对应的业务逻辑，供 `DebugArtifactsService` 使用。"""
        return str(debug_logger.latest_error_summary_file)

    def open_path(self, file_path: str):
        """打开 `path` 对应的文件、页面或资源，供 `DebugArtifactsService` 使用。"""
        if not os.path.exists(file_path):
            raise DebugActionError(f"文件不存在: {file_path}")
        try:
            if os.name == "nt":
                os.startfile(file_path)
            else:
                subprocess.Popen(["xdg-open", file_path])
        except (AttributeError, OSError, subprocess.SubprocessError) as exc:
            raise DebugActionError(str(exc)) from exc

    def open_latest_log(self):
        """打开 `latest_log` 对应的文件、页面或资源，供 `DebugArtifactsService` 使用。"""
        self.open_path(self.latest_log_path())

    def open_latest_error_summary(self):
        """打开 `latest_error_summary` 对应的文件、页面或资源，供 `DebugArtifactsService` 使用。"""
        self.open_path(self.latest_error_summary_path())

    def copy_trace_id(self, clipboard, trace_id: str | None):
        """复制 `trace_id` 对应的数据或标识到目标位置，供 `DebugArtifactsService` 使用。"""
        if not trace_id:
            raise DebugActionError("当前未找到可复制的 trace_id")
        clipboard.setText(trace_id)
