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
        super().__init__()
        self.keyword = keyword
        self.config = config
        self.is_running = True
        self.trace_prefix = self.__class__.__name__.replace("Spider", "").lower() or "spider"
        # The spider thread waits on this event while the UI shows a selection dialog.
        self._resume_event = threading.Event()
        self._selection_result = None

    def stop(self):
        self.is_running = False
        self._resume_event.set()
        self.sig_log.emit("🛑 正在停止任务...")

    def run(self):
        raise NotImplementedError("Subclasses must implement run().")

    def log(self, msg: str):
        self.sig_log.emit(msg)

    def debug_state(self, action: str, message: str = "", status_code=None, context=None, details=None, trace_id=None):
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
        return debug_logger.new_trace_id(f"{self.trace_prefix}-{suffix}")

    def ensure_trace_id(self, meta: dict | None = None, suffix: str = "task") -> str:
        if meta is None:
            return self.new_trace_id(suffix)
        trace_id = meta.get("trace_id")
        if not trace_id:
            trace_id = self.new_trace_id(suffix)
            meta["trace_id"] = trace_id
        return trace_id

    def emit_video(self, url: str, title: str, source: str, meta: dict | None = None):
        item = VideoItem(url=url, title=title, source=source)
        if meta:
            item.meta = meta
        self.ensure_trace_id(item.meta, suffix=source)
        self.sig_item_found.emit(item)

    def ask_user_selection(self, items: list) -> list | None:
        # The spider thread blocks here until the UI resumes it.
        self._resume_event.clear()
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
