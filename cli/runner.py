"""CLIRunner：CLI 核心执行器，完全对齐 GUI ApplicationController 的行为。

GUI 流程（ApplicationController）：
1. on_start_crawl → _create_spider → _bind_spider_signals → spider.start()
2. spider.run() 中调用 self.ask_user_selection(items)
3. _on_spider_select_tasks → window.show_selection_dialog → spider.resume_from_ui(indices)
4. spider.run() 中调用 self.emit_video(url, title, source, meta) → sig_item_found
5. _on_spider_item_found → videos[id]=item + window.add_video_row + dl_manager.add_task(item, save_dir)
6. dl_manager → DownloadWorker → sig_start/sig_progress/sig_finished/sig_error
7. _on_task_started/progress/finished/error → _apply_video_state + window.update_video_status
8. spider.run() 结束 → sig_finished → _on_spider_finished → set_crawl_running_state(False)

CLI 对齐方式：
- 步骤 2-3：monkey-patch ask_user_selection 为同步版，直接调 selection_strategy.select()
- 步骤 4-5：sig_item_found → 收集 item + dl_manager.add_task(item, save_dir)
- 步骤 6-7：dl_manager 信号 → 更新 item 状态（status/progress/local_path）
- 步骤 8：sig_finished → 标记完成

关键差异：CLI 没有 window，所有 UI 更新都变成内存状态更新。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

# 必须在导入 Qt 之前设置 (与 web_main.py 一致)
os.environ.setdefault("PYTHONUNBUFFERED", "1")


def _ensure_qt_app():
    """确保 QApplication 单例存在 (spider 派生自 QThread，必须有 QApplication)。"""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as e:
        raise RuntimeError(
            "PyQt6 未安装。CLI 必须在 Qt 嵌入式进程中运行 spider。\n"
            "请安装: pip install PyQt6"
        ) from e

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
    return app


class CLIRunner:
    """CLI 核心执行器：完全对齐 GUI ApplicationController 的行为。"""

    def __init__(
        self,
        source: str,
        keyword: str,
        save_dir: str = "downloads",
        selection_strategy=None,
        config: dict | None = None,
        verbose: bool = True,
        log_to_stderr: bool = True,
        timeout: float | None = None,
        download: bool = True,
    ):
        """初始化 CLI 执行器。

        Args:
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            keyword: 搜索关键词 / 链接 / 用户 ID
            save_dir: 保存目录
            selection_strategy: 二次选择策略 (默认 AutoSelection)
            config: 平台特定参数
            verbose: 是否输出详细信息
            log_to_stderr: spider 日志是否输出到 stderr
            timeout: 超时秒数 (None=无限)
            download: 是否触发下载 (True=与 GUI 一致自动下载, False=只收集不下载)
        """
        from cli.selection import AutoSelection

        self.source = source
        self.keyword = keyword
        self.save_dir = save_dir
        self.config = dict(config or {})
        self.selection_strategy = selection_strategy or AutoSelection()
        self.verbose = verbose
        self.log_to_stderr = log_to_stderr
        self.timeout = timeout
        self.download = download

        # 运行状态（与 GUI ApplicationController 对称）
        self.videos: dict[str, Any] = {}    # video_id → VideoItem（与 GUI self.videos 对称）
        self.logs: list[str] = []           # spider 日志
        self.selection_count: int = 0       # ask_user_selection 调用次数
        self.error: str | None = None
        self.finished: bool = False
        self._spider = None
        self._dl_manager = None

    def _log(self, msg: str) -> None:
        """CLI 内部日志。"""
        if self.verbose:
            sys.stderr.write(f"[CLI] {msg}\n")
            sys.stderr.flush()

    # ---- 与 GUI ApplicationController._connect_window_signals 对称 ----

    def _on_log(self, msg: str) -> None:
        """spider.sig_log 回调（与 GUI window.append_log 对称）。"""
        self.logs.append(str(msg))
        if self.log_to_stderr:
            sys.stderr.write(f"{msg}\n")
            sys.stderr.flush()

    def _on_item_found(self, item) -> None:
        """spider.sig_item_found 回调（与 GUI _on_spider_item_found 完全对齐）。

        GUI 行为：
        1. item.status = "⏳ 等待中"
        2. item.progress = 0
        3. self.videos[item.id] = item
        4. window.add_video_row(item)
        5. dl_manager.add_task(item, save_dir)
        """
        item.status = "⏳ 等待中"
        item.progress = 0
        self.videos[item.id] = item

        if self.download and self._dl_manager:
            # 与 GUI 完全一致：立即入队下载
            self._dl_manager.add_task(item, self.save_dir)

    def _on_select_tasks(self, items: list) -> None:
        """spider.sig_select_tasks 回调（与 GUI _on_spider_select_tasks 对称）。

        GUI 行为：window.show_selection_dialog(items) → spider.resume_from_ui(indices)
        CLI 行为：selection_strategy.select(items) → spider.resume_from_ui(indices)

        注意：由于 ask_user_selection 被 monkey-patch 为同步版，
        sig_select_tasks 信号不会被 emit（同步版直接返回 indices）。
        但为了安全，这里也处理信号触发的情况。
        """
        self._do_select_and_resume(items)

    def _do_select_and_resume(self, items: list) -> None:
        """执行二次选择并恢复 spider 线程。"""
        self.selection_count += 1
        prompt = f"二次选择 #{self.selection_count}: {len(items)} 个候选"
        self._log(prompt)
        try:
            indices = self.selection_strategy.select(items, prompt=prompt)
        except Exception as e:
            self._log(f"选择策略异常: {e}，默认全选")
            indices = list(range(len(items)))
        if indices is None:
            self._log("用户取消，本次选择返回空")
            indices = []
        self._log(f"  → 选中 {len(indices)} 项: {indices[:10]}{'...' if len(indices) > 10 else ''}")

        # 与 GUI _on_spider_select_tasks 完全一致：调 resume_from_ui
        if self._spider:
            self._spider.resume_from_ui(indices)

    def _on_finished(self) -> None:
        """spider.sig_finished 回调（与 GUI _on_spider_finished 对称）。"""
        self.finished = True
        self._log("✅ 爬虫任务结束")

    # ---- 与 GUI ApplicationController._connect_download_signals 对称 ----

    def _on_task_started(self, video_id: str) -> None:
        """下载开始（与 GUI _on_task_started 对齐：status="⏳ 下载中...", progress=0）。"""
        self._apply_video_state(video_id, status="⏳ 下载中...", progress=0)

    def _on_task_progress(self, video_id: str, progress: int) -> None:
        """下载进度（与 GUI _on_task_progress 对齐：只更新 progress）。"""
        self._apply_video_state(video_id, progress=progress)

    def _on_task_finished(self, video_id: str) -> None:
        """下载完成（与 GUI _on_download_finished 对齐：status="✅ 完成", progress=100）。"""
        item = self._apply_video_state(video_id, status="✅ 完成", progress=100)
        if item and self.log_to_stderr:
            sys.stderr.write(f"✅ 下载完成: {item.title}\n")
            sys.stderr.flush()

    def _on_task_error(self, video_id: str, error: str) -> None:
        """下载失败（与 GUI _on_download_error 对齐：status="❌ 失败"）。"""
        item = self._apply_video_state(video_id, status="❌ 失败")
        if item and self.log_to_stderr:
            sys.stderr.write(f"❌ 下载失败 [{item.title}]: {error}\n")
            sys.stderr.flush()

    def _apply_video_state(self, vid: str, *, status: str | None = None, progress: int | None = None):
        """更新内存中的视频状态（与 GUI _apply_video_state 对齐）。"""
        item = self.videos.get(vid)
        if not item:
            return None
        if status is not None:
            item.status = status
        if progress is not None:
            item.progress = progress
        return item

    # ---- monkey-patch ask_user_selection ----

    def _make_ask_user_selection(self):
        """生成同步版的 ask_user_selection 闭包。

        GUI 行为：ask_user_selection → sig_select_tasks.emit(items) → wait(_resume_event)
        CLI 行为：ask_user_selection → selection_strategy.select(items) → 直接返回 indices

        关键：spider 线程调用 ask_user_selection 时，不再走 Qt 信号+事件等待，
        而是直接同步调用 selection_strategy.select()，返回选中的索引列表。
        这样 spider 线程不需要被 _resume_event 阻塞。
        """
        strategy = self.selection_strategy
        runner = self  # 闭包引用

        def ask_user_selection_sync(spider_self, items):
            """同步版 ask_user_selection：直接调 selection_strategy，不走 Qt 信号。"""
            runner.selection_count += 1
            prompt = f"二次选择 #{runner.selection_count}: {len(items)} 个候选"
            runner._log(prompt)
            try:
                indices = strategy.select(items, prompt=prompt)
            except Exception as e:
                runner._log(f"选择策略异常: {e}，默认全选")
                indices = list(range(len(items)))
            if indices is None:
                indices = []
            runner._log(f"  → 选中 {len(indices)} 项: {indices[:10]}{'...' if len(indices) > 10 else ''}")
            return indices

        return ask_user_selection_sync

    # ---- 绑定信号 ----

    def _patch_spider(self, spider) -> None:
        """monkey-patch spider 实例（与 GUI _bind_spider_signals 对称）。"""
        from types import MethodType

        # 替换 ask_user_selection 为同步版
        spider.ask_user_selection = MethodType(self._make_ask_user_selection(), spider)

        # 绑定 Qt 信号（与 GUI _bind_spider_signals 一致）
        spider.sig_log.connect(self._on_log)
        spider.sig_item_found.connect(self._on_item_found)
        spider.sig_select_tasks.connect(self._on_select_tasks)  # 安全兜底
        spider.sig_finished.connect(self._on_finished)

    def _connect_download_signals(self):
        """绑定下载管理器信号（与 GUI _connect_download_signals 完全一致）。"""
        if self._dl_manager:
            self._dl_manager.task_started.connect(self._on_task_started)
            self._dl_manager.task_progress.connect(self._on_task_progress)
            self._dl_manager.task_finished.connect(self._on_task_finished)
            self._dl_manager.task_error.connect(self._on_task_error)

    # ---- 主执行流程 ----

    def run(self) -> dict:
        """执行爬虫并返回结果（与 GUI on_start_crawl 流程完全对齐）。

        GUI 流程：
        1. _create_spider(source_id, keyword, config)
        2. window.append_log("🟢 启动任务 | 模式: ...")
        3. window.set_crawl_running_state(True)
        4. self.current_spider = spider
        5. _bind_spider_signals(spider)
        6. spider.start()
        7. (等待 spider 完成)
        8. _on_spider_finished → set_crawl_running_state(False)

        Returns:
            dict: {
                "status": "ok" | "error" | "timeout" | "cancelled",
                "source": "douyin",
                "keyword": "...",
                "save_dir": "...",
                "items": [...],          # 视频项目列表（含最终 status/progress/local_path）
                "logs": [...],           # spider 日志
                "selection_count": 0,    # 二次选择调用次数
                "elapsed": 12.3,         # 耗时 (秒)
                "error": "..."           # 错误信息 (如果失败)
            }
        """
        start = time.time()
        _ensure_qt_app()

        from app.core.plugin_registry import registry

        # 步骤 1：创建 spider（与 GUI _create_spider 一致）
        plugin = registry.get_plugin(self.source)
        if plugin is None:
            return {
                "status": "error",
                "error": f"未知平台: {self.source}。支持: {[p.id for p in registry.get_all_plugins()]}",
            }

        spider_cls = plugin.get_spider_class()
        spider = spider_cls(keyword=self.keyword, config=self.config)
        self._spider = spider

        # 步骤 2：创建下载管理器（与 GUI ApplicationController.__init__ 一致）
        if self.download:
            from app.config import cfg
            from app.core.download_manager import DownloadManager
            self._dl_manager = DownloadManager(
                max_concurrent=cfg.get("download", "max_concurrent", 3)
            )
            self._connect_download_signals()

        # 步骤 3：绑定信号 + monkey-patch（与 GUI _bind_spider_signals 一致）
        self._patch_spider(spider)

        # 步骤 4：启动 spider（与 GUI on_start_crawl 一致）
        self._log(f"🟢 启动任务 | 模式: {plugin.name} | 关键词: {self.keyword}")
        spider.start()

        # 步骤 5：等待 spider 完成（与 GUI 事件循环等待一致）
        if self.timeout is not None:
            finished_in_time = spider.wait(int(self.timeout * 1000))
            if not finished_in_time:
                self._log(f"spider 超过 {self.timeout}s 未完成，强制停止")
                spider.stop()
                spider.wait(5000)
                # 等待下载完成
                self._wait_downloads(timeout=30)
                return self._build_result("timeout", start, f"timeout after {self.timeout}s")
        else:
            spider.wait()

        # 步骤 6：等待下载完成（GUI 中下载是异步的，CLI 需要等所有下载结束）
        if self.download and self._dl_manager:
            self._wait_downloads(timeout=300)

        elapsed = round(time.time() - start, 2)
        self._log(f"spider 已结束, 耗时 {elapsed}s, 收集到 {len(self.videos)} 个项目, 二次选择 {self.selection_count} 次")

        return self._build_result("ok" if not self.error else "error", start)

    def _wait_downloads(self, timeout: float = 300) -> None:
        """等待所有下载任务完成。

        GUI 中下载是异步的（用户可以看到进度条实时更新），
        CLI 中需要等所有下载结束才能返回最终结果。
        """
        if not self._dl_manager:
            return

        deadline = time.time() + timeout
        while time.time() < deadline:
            # 检查是否还有活跃的 worker
            with self._dl_manager._workers_lock:
                active = len(self._dl_manager.workers)
            # 检查队列是否还有任务
            queued = self._dl_manager.queue.qsize()
            if active == 0 and queued == 0:
                break
            # 处理 Qt 事件（DownloadWorker 是 QThread，需要 processEvents）
            try:
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    app.processEvents()
            except Exception:
                pass
            time.sleep(0.5)

    def _build_result(self, status: str, start_time: float, error: str | None = None) -> dict:
        """构建返回结果（items 包含最终 status/progress/local_path，与 GUI 最终状态一致）。"""
        elapsed = round(time.time() - start_time, 2)

        # 把 videos dict 转为 list（与 GUI 最终状态一致）
        items = []
        for vid, item in self.videos.items():
            try:
                items.append(item.to_dict())
            except Exception as e:
                self._log(f"item 转换失败: {e}")

        return {
            "status": status,
            "source": self.source,
            "keyword": self.keyword,
            "save_dir": self.save_dir,
            "items": items,
            "logs": self.logs,
            "selection_count": self.selection_count,
            "elapsed": elapsed,
            "error": error or self.error,
        }

    def stop(self) -> None:
        """中途停止爬虫（与 GUI on_stop_crawl 对齐）。"""
        if self._spider and self._spider.isRunning():
            self._spider.stop()
        if self._dl_manager:
            self._dl_manager.stop_all()


def run_search(
    source: str,
    keyword: str,
    save_dir: str = "downloads",
    selection_strategy=None,
    download: bool = True,
    **config,
) -> dict:
    """便捷函数：启动一次爬虫并返回结果。

    Example:
        result = run_search("douyin", "测试关键词", max_items=20, save_dir="downloads")
    """
    runner = CLIRunner(
        source=source,
        keyword=keyword,
        save_dir=save_dir,
        selection_strategy=selection_strategy,
        config=config,
        download=download,
    )
    return runner.run()
