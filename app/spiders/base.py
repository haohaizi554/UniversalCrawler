"""Base spider helpers used by all platforms."""

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from app.debug_logger import debug_logger
from app.models import VideoItem


class BaseSpider(QThread):
    """Common spider thread base with UI selection helpers."""

    sig_log = pyqtSignal(str)
    sig_item_found = pyqtSignal(VideoItem)
    sig_finished = pyqtSignal()
    sig_select_tasks = pyqtSignal(list)

    def __init__(self, keyword: str, config: dict):
        """初始化当前实例并准备运行所需的状态，供 `BaseSpider` 使用。"""
        super().__init__()
        self.keyword = keyword
        self.config = config
        self.is_running = True
        self.trace_prefix = self.__class__.__name__.replace("Spider", "").lower() or "spider"
        # The spider thread waits on this event while the UI shows a selection dialog.
        self._resume_event = threading.Event()
        self._selection_result = None

    def stop(self):
        """执行 `stop` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        self.is_running = False
        self._resume_event.set()
        self.sig_log.emit("🛑 正在停止任务...")

    def run(self):
        """执行当前对象或脚本的主流程，供 `BaseSpider` 使用。"""
        raise NotImplementedError("Subclasses must implement run().")

    def log(self, msg: str):
        """执行 `log` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        self.sig_log.emit(msg)

    def debug_state(self, action: str, message: str = "", status_code=None, context=None, details=None, trace_id=None):
        """执行 `debug_state` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        if isinstance(context, dict):
            trace_id = trace_id or context.get("trace_id")
        if not trace_id and isinstance(details, dict):
            trace_id = details.get("trace_id")
        debug_logger.log(
            component=self.__class__.__name__,
            action=action,
            message=message,
            status_code=status_code,
            context=context,
            details=details,
            trace_id=trace_id,
        )

    def debug_api(self, api_name: str, request=None, response_summary=None, message: str = "", status_code=None):
        """执行 `debug_api` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        trace_id = None
        if isinstance(request, dict):
            trace_id = request.get("trace_id")
        if not trace_id and isinstance(response_summary, dict):
            trace_id = response_summary.get("trace_id")
        debug_logger.log_api(
            component=self.__class__.__name__,
            api_name=api_name,
            request=request,
            response_summary=response_summary,
            message=message,
            status_code=status_code,
            trace_id=trace_id,
        )

    def new_trace_id(self, suffix: str = "task") -> str:
        """执行 `new_trace_id` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        return debug_logger.new_trace_id(f"{self.trace_prefix}-{suffix}")

    def ensure_trace_id(self, meta: dict | None = None, suffix: str = "task") -> str:
        """执行 `ensure_trace_id` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        if meta is None:
            return self.new_trace_id(suffix)
        trace_id = meta.get("trace_id")
        if not trace_id:
            trace_id = self.new_trace_id(suffix)
            meta["trace_id"] = trace_id
        return trace_id

    #视频发现与分发
    def emit_video(self, url: str, title: str, source: str, meta: dict | None = None):
        """执行 `emit_video` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        item = VideoItem(url=url, title=title, source=source)
        if meta:
            item.meta = meta
        self.ensure_trace_id(item.meta, suffix=source)
        self.sig_item_found.emit(item)

    #暂停爬虫线程，向 UI 发送选择请求，等待用户选择结果
    def ask_user_selection(self, items: list) -> list | None:
        # The spider thread blocks here until the UI resumes it.
        """执行 `ask_user_selection` 对应的业务逻辑，供 `BaseSpider` 使用。"""
        self._resume_event.clear()#准备进入等待状态
        self._selection_result = None
        self.sig_select_tasks.emit(items)
        while self.is_running:
            if self._resume_event.wait(timeout=1.0):
                break
        if not self.is_running:
            return None
        return self._selection_result

    def resume_from_ui(self, selected_indices):
        """Resume a spider thread after the UI collected user choices."""
        self._selection_result = selected_indices
        self._resume_event.set()
