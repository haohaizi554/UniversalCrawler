import os
import subprocess
from pathlib import Path

from app.debug_logger import debug_logger
from app.exceptions import DebugActionError


class DebugArtifactsService:
    """负责打开调试产物和复制 trace_id。"""

    def __init__(self):
        self.logs_dir = debug_logger.logs_dir

    def latest_log_path(self) -> str:
        return str(debug_logger.latest_file)

    def latest_error_summary_path(self) -> str:
        return str(debug_logger.latest_error_summary_file)

    def open_path(self, file_path: str):
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
        self.open_path(self.latest_log_path())

    def open_latest_error_summary(self):
        self.open_path(self.latest_error_summary_path())

    def copy_trace_id(self, clipboard, trace_id: str | None):
        if not trace_id:
            raise DebugActionError("当前未找到可复制的 trace_id")
        clipboard.setText(trace_id)
