# app/spiders/base_spider.py
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from app.models import VideoItem, AppConfig

class BaseSpider(QThread):
    # 基础信号
    sig_log = pyqtSignal(str)
    sig_item_found = pyqtSignal(VideoItem)
    sig_finished = pyqtSignal()
    # 参数: (list) 包含标题的字典列表
    sig_select_tasks = pyqtSignal(list)
    def __init__(self, keyword: str, config: dict):
        super().__init__()
        self.keyword = keyword
        self.config = config
        self.is_running = True
        # 同步锁，用于暂停爬虫等待UI响应
        self._resume_event = threading.Event()
        self._selection_result = None  # 存储用户返回的索引列表
    def stop(self):
        self.is_running = False
        self._resume_event.set()  # 防止卡死在等待中
        self.sig_log.emit("🛑 正在停止任务...")
    def run(self):
        raise NotImplementedError("子类必须实现 run 方法")
    # ================= 辅助方法 =================
    def log(self, msg: str):
        self.sig_log.emit(msg)
    def emit_video(self, url: str, title: str, source: str, meta: dict = None):
        item = VideoItem(url=url, title=title, source=source)
        if meta: item.meta = meta
        self.sig_item_found.emit(item)
    def ask_user_selection(self, items: list) -> list:
        # [核心升级] 阻塞当前爬虫线程，等待主线程(UI)的用户选择结果
        # :param items: [{'title': 'xxx'}, ...]
        # :return: 用户选中的索引列表 [0, 2, 5...]，如果取消则返回 None
        self._resume_event.clear()  # 重置信号灯
        self._selection_result = None
        # 1. 发送信号给 UI，让 UI 弹窗
        self.sig_select_tasks.emit(items)
        # 2. 阻塞等待，直到 UI 设置 _resume_event
        # 每秒醒来一次检查 is_running，防止无法停止
        while self.is_running:
            if self._resume_event.wait(timeout=1.0):
                break
        if not self.is_running:
            return None
        return self._selection_result
    def resume_from_ui(self, selected_indices):
        """由 UI 线程调用，唤醒爬虫"""
        self._selection_result = selected_indices
        self._resume_event.set()  # 绿灯，爬虫继续跑