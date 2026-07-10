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

from shared.controller_session import ControllerSessionMixin
from shared.selection_runtime import AutoSelection, SelectionBridge, build_selection_prompt, format_selection_result
from shared.spider_session_runtime import SpiderSession, SpiderSessionBindings

# 保持 CLI 输出实时刷新，便于下载和选择流程即时反馈
os.environ.setdefault("PYTHONUNBUFFERED", "1")

def _video_status_enum():
    from app.core.state import VideoStatus

    return VideoStatus

class CLIRunner(ControllerSessionMixin):
    """CLI 核心执行器：完全对齐 GUI ApplicationController 的行为。"""

    DOWNLOAD_LOG_COMPONENT = "CLIRunner"
    DOWNLOAD_FINISHED_STATUS_CODE = "CLI_DL_FINISH"
    DOWNLOAD_ERROR_STATUS_CODE = "CLI_DL_ERROR"
    DOWNLOAD_FINISHED_MESSAGE = "CLI 下载任务完成"
    DOWNLOAD_ERROR_MESSAGE = "CLI 下载任务失败"

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
        self.source = source
        # 与 GUI inp_search.text().strip() 对齐：去除前后空白
        self.keyword = keyword.strip() if isinstance(keyword, str) else keyword
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
        self._spider_session = SpiderSession()
        self._cancelled: bool = False       # 用户取消标志（与 SKILL.md "cancelled" 状态对齐）
        self._progress_logged_pct: dict[str, int] = {}
        self._last_download_heartbeat_at: float = 0.0

    def _log(self, msg: str) -> None:
        """CLI 内部日志。"""
        if self.verbose:
            sys.stderr.write(f"[CLI] {msg}\n")
            sys.stderr.flush()

    def _debug_log(self, action: str, message: str, status_code: str,
                   level: str | None = None, details: dict | None = None) -> None:
        """结构化日志（与 GUI ApplicationController 和 WebController 对齐）。

        使用 debug_logger 记录关键事件，便于 CLI 问题排查。
        不影响 GUI/Web 的日志行为。
        """
        try:
            from app.debug_logger import debug_logger
            debug_logger.log(
                component="CLIRunner",
                action=action,
                message=message,
                status_code=status_code,
                level=level,
                details=details or {},
            )
        except Exception:
            pass  # debug_logger 不可用时不影响 CLI 功能

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

        CLI/SDK/API 差异：download=False 时状态为 "📋 已收集"（只搜索不下载），
        与 GUI 的 "⏳ 等待中" 区分开，避免误导用户以为正在等待下载。
        """
        if self.download:
            self._prepare_pending_item(item)
        else:
            item.status = "📋 已收集"
            item.progress = 0
        self.videos[item.id] = item

        if self.download and self._dl_manager:
            # 与 GUI 完全一致：立即入队下载
            self._dl_manager.add_task(item, self.save_dir)

        # 与 GUI/Web 对齐：记录 item 发现日志
        self._debug_log("item_found", "CLI 发现可下载资源", "CLI_ITEM_FOUND",
                         details={"video_id": item.id, "title": item.title, "source": item.source})

    def _on_items_found(self, items: list) -> None:
        """spider.sig_items_found 回调：批量收集并批量入下载队列。"""
        video_items = list(items or [])
        if not video_items:
            return
        if len(video_items) == 1:
            self._on_item_found(video_items[0])
            return

        accepted_items = []
        for item in video_items:
            if self.download:
                self._prepare_pending_item(item)
            else:
                item.status = "📋 已收集"
                item.progress = 0
            self.videos[item.id] = item
            accepted_items.append(item)

        if self.download and self._dl_manager and accepted_items:
            add_tasks = getattr(self._dl_manager, "add_tasks", None)
            if callable(add_tasks):
                add_tasks(accepted_items, self.save_dir)
            else:
                for item in accepted_items:
                    self._dl_manager.add_task(item, self.save_dir)

        for item in accepted_items:
            self._debug_log("item_found", "CLI 发现可下载资源", "CLI_ITEM_FOUND",
                            details={"video_id": item.id, "title": item.title, "source": item.source})

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
        _prompt, indices = self._run_selection(items, strategy=self.selection_strategy)

        # 与 GUI _on_spider_select_tasks 完全一致：调 resume_from_ui
        if self._spider:
            self._spider.resume_from_ui(indices)

    def _run_selection(self, items: list, *, strategy) -> tuple[str, list[int]]:
        """统一执行一次二次选择并输出摘要。"""
        self.selection_count += 1
        prompt = build_selection_prompt(self.selection_count, len(items))
        self._log(prompt)
        try:
            indices = strategy.select(items, prompt=prompt)
        except Exception as exc:
            self._log(f"选择策略异常: {exc}，返回空选择")
            indices = []

        if indices is None:
            self._cancelled = True
            self._log("用户取消选择，正在停止爬虫...")
            indices = []

        self._log(format_selection_result(indices))
        return prompt, indices

    def _on_finished(self) -> None:
        """spider.sig_finished 回调（与 GUI _on_spider_finished 对称）。"""
        self.finished = True
        self._spider = None  # 与 GUI/Web 一致：清空 spider 引用
        self._log("✅ 爬虫任务结束")
        # 与 GUI/Web 对齐：记录爬虫完成日志
        self._debug_log("crawl_finished", "CLI 爬虫任务结束", "CLI_CRAWL_FINISH")

    # ---- 与 GUI ApplicationController._connect_download_signals 对称 ----

    def _after_task_started(self, video_id: str, item) -> None:
        self._progress_logged_pct.pop(video_id, None)
        if item and self.log_to_stderr:
            prefix = "⏳ 大文件下载启动" if self._is_large_transfer(item) else "⏳ 开始下载"
            sys.stderr.write(f"{prefix}: {item.title}\n")
            sys.stderr.flush()

    def _after_task_progress(self, video_id: str, item, progress: int) -> None:
        if not item or not self.log_to_stderr:
            return
        if not self._should_log_progress(item, progress):
            return
        bar = self._render_progress_bar(progress)
        sys.stderr.write(f"📥 {item.title[:28]} {bar} {progress}%\n")
        sys.stderr.flush()

    def _after_task_finished(self, video_id: str, item) -> None:
        self._progress_logged_pct.pop(video_id, None)

    def _after_task_error(self, video_id: str, item, error: str) -> None:
        self._progress_logged_pct.pop(video_id, None)

    def _publish_video_state(self, vid: str, item, *, requested_progress: int | None) -> None:
        """CLI 端暂不额外广播视频状态事件，仅复用统一状态更新链。"""
        return None

    def _emit_controller_log(
        self,
        message: str,
        *,
        trace_id: str | None = None,
        source: str = "Controller",
        level: str = "INFO",
    ) -> None:
        if not self.log_to_stderr:
            return
        sys.stderr.write(f"{message}\n")
        sys.stderr.flush()

    def _build_download_finished_log_details(self, item) -> dict[str, Any]:
        return {
            "video_id": item.id,
            "title": item.title,
            "local_path": item.local_path or "",
        }

    def _build_download_error_log_details(self, item, error: str) -> dict[str, Any]:
        return {
            "video_id": item.id,
            "title": item.title,
            "error": error,
        }

    def _format_download_finished_message(self, item) -> str:
        local_path = item.local_path or ""
        return f"✅ 下载完成: {item.title}" + (f" → {local_path}" if local_path else "")

    def _format_download_error_message(self, item, error: str) -> str:
        return f"❌ 下载失败 [{item.title}]: {error}"

    @staticmethod
    def _render_progress_bar(progress: int, width: int = 18) -> str:
        """渲染简易文本进度条。"""
        progress = max(0, min(100, int(progress)))
        filled = round(progress / 100 * width)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    @staticmethod
    def _is_large_transfer(item) -> bool:
        """判断是否属于用户感知上容易“像卡死”的大文件任务。"""
        meta = getattr(item, "meta", {}) or {}
        try:
            size_mb = float(meta.get("size_mb", 0) or 0)
        except (TypeError, ValueError):
            size_mb = 0
        try:
            duration = float(meta.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0
        content_type = str(meta.get("content_type", "") or "").lower()
        return size_mb >= 100 or duration >= 300 or (content_type in {"video", "movie"} and duration >= 180)

    def _should_log_progress(self, item, progress: int) -> bool:
        """节流下载进度输出，避免终端刷屏。"""
        last_logged = self._progress_logged_pct.get(item.id, -1)
        if progress >= 100:
            self._progress_logged_pct[item.id] = 100
            return True
        step = 5 if self._is_large_transfer(item) else 20
        bucket = int(progress // step) * step
        if bucket <= last_logged:
            return False
        self._progress_logged_pct[item.id] = bucket
        return progress > 0

    def _emit_download_heartbeat(self) -> None:
        """长下载期间输出心跳，避免用户误判为卡死。"""
        if not self.log_to_stderr:
            return
        now = time.time()
        if now - self._last_download_heartbeat_at < 8:
            return
        active_items = []
        for item in self.videos.values():
            if item.status in ("⏳ 等待中", "⏳ 下载中..."):
                active_items.append(f"{item.title[:20]} {self._render_progress_bar(item.progress)} {item.progress}%")
        if not active_items:
            return
        self._last_download_heartbeat_at = now
        sys.stderr.write("⏱️ 下载进行中: " + " | ".join(active_items[:3]) + "\n")
        sys.stderr.flush()

    # ---- monkey-patch ask_user_selection ----

    def _make_ask_user_selection(self):
        """生成同步版的 ask_user_selection 闭包。

        GUI 行为：ask_user_selection → sig_select_tasks.emit(items) → wait(_resume_event)
        CLI 行为：ask_user_selection → selection_strategy.select(items) → 直接返回 indices

        关键：spider 线程调用 ask_user_selection 时，不再走 Qt 信号+事件等待，
        而是直接同步调用 selection_strategy.select()，返回选中的索引列表。
        这样 spider 线程不需要被 _resume_event 阻塞。
        """
        runner = self
        bridge = None

        def on_prompt(prompt: str, items: list) -> None:
            runner.selection_count = bridge.selection_count
            runner._log(prompt)

        def on_error(exc: Exception, prompt: str, items: list) -> None:
            runner.selection_count = bridge.selection_count
            runner._log(f"选择策略异常: {exc}，返回空选择")

        def on_result(prompt: str, indices: list[int], cancelled: bool, items: list) -> None:
            runner.selection_count = bridge.selection_count
            if cancelled:
                runner._cancelled = True
                runner._log("用户取消选择，正在停止爬虫...")
            runner._log(format_selection_result(indices))

        bridge = SelectionBridge(
            strategy=self.selection_strategy,
            on_prompt=on_prompt,
            on_error=on_error,
            on_result=on_result,
        )

        def ask_user_selection_sync(spider_self, items):
            """同步版 ask_user_selection：直接调 selection_strategy，不走 Qt 信号。"""
            if runner._cancelled:
                runner._log("用户已取消，跳过后续选择")
                return []
            return bridge.build_sync_ask_user_selection()(spider_self, items)

        return ask_user_selection_sync

    # ---- 绑定信号 ----

    def _patch_spider(self, spider) -> None:
        """只负责 monkey-patch 选择行为，信号绑定统一交给 SpiderSession。"""
        from types import MethodType
        # 替换 ask_user_selection 为同步版
        spider.ask_user_selection = MethodType(self._make_ask_user_selection(), spider)

    def _connect_download_signals(self):
        """绑定下载管理器回调（与 GUI _connect_download_signals 语义一致）。"""
        if self._dl_manager:
            self._dl_manager.task_started.connect(self._on_task_started)
            self._dl_manager.task_progress.connect(self._on_task_progress)
            self._dl_manager.task_finished.connect(self._on_task_finished)
            self._dl_manager.task_error.connect(self._on_task_error)

    def _wait_spider(self, spider, timeout: float | None = None) -> bool:
        """等待 spider 结束。

        Returns:
            bool: True=正常结束，False=超时
        """
        deadline = time.time() + timeout if timeout is not None else None
        while True:
            try:
                running = spider.isRunning()
            except Exception:
                # 兜底：如果 spider 不支持 isRunning，则退回原生 wait
                if timeout is not None:
                    return bool(spider.wait(int(timeout * 1000)))
                spider.wait()
                return True

            if not running:
                break

            if deadline is not None and time.time() >= deadline:
                return False

            time.sleep(0.05)
        return True

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

        # 步骤 1：创建 spider（与 GUI _create_spider 一致）
        from app.core.plugin_registry import registry

        plugin = registry.get_plugin(self.source)
        if plugin is None:
            return {
                "status": "error",
                "error": f"未知平台: {self.source}。支持: {[p.id for p in registry.get_all_plugins()]}",
            }
        try:
            _, spider = self._spider_session.create_spider(self.source, self.keyword, self.config)
        except Exception as exc:
            # 与 WebController start_crawl 对齐：捕获 spider 创建异常，返回结构化错误
            self._log(f"❌ 创建爬虫失败: {exc}")
            return {
                "status": "error",
                "error": f"创建爬虫失败: {exc}",
            }
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
        self._spider_session.bind_spider(
            spider,
            SpiderSessionBindings(
                on_log=self._on_log,
                on_item_found=self._on_item_found,
                on_items_found=self._on_items_found,
                on_select_tasks=self._on_select_tasks,
                on_finished=self._on_finished,
                patch_spider=self._patch_spider,
            ),
        )

        # 步骤 4：启动 spider（与 GUI on_start_crawl 一致）
        self._log(f"🟢 启动任务 | 模式: {plugin.name} | 关键词: {self.keyword}")
        # 与 GUI/Web 对齐：记录爬虫启动日志
        self._debug_log("start_crawl", "CLI 启动爬虫任务", "CLI_CRAWL_START",
                         details={
                             "keyword": self.keyword,
                             "source_id": self.source,
                             "plugin_name": plugin.name,
                             "active_config": self._summarize_active_config(self.config),
                         })
        spider.start()

        # 步骤 5：等待 spider 完成（与 GUI 事件循环等待一致）
        if self.timeout is not None:
            finished_in_time = self._wait_spider(spider, timeout=self.timeout)
            if not finished_in_time:
                self._log(f"spider 超过 {self.timeout}s 未完成，强制停止")
                spider.stop()
                spider.wait(5000)
                # 等待下载完成（给 30s 缓冲）
                dl_timed_out = self._wait_downloads(timeout=30)
                # 清理：停止仍在运行的下载线程（与 GUI shutdown 一致）
                if self._dl_manager:
                    self._dl_manager.stop_all()
                # 超时检测：标记仍在下载中的项目
                if dl_timed_out:
                    video_status = _video_status_enum()
                    for item in self.videos.values():
                        if item.status in (video_status.DOWNLOADING.label, video_status.PENDING.label):
                            item.status = video_status.TIMED_OUT.label
                            item.meta["download_error"] = "下载超时 (30s)"
                # 与 GUI _on_spider_finished 对齐：清空 spider 引用，避免悬空引用
                self._spider = None
                return self._build_result("timeout", start, f"timeout after {self.timeout}s")
        else:
            self._wait_spider(spider)

        # 步骤 6：等待下载完成（GUI 中下载是异步的，CLI 需要等所有下载结束）
        download_timed_out = False
        if self.download and self._dl_manager:
            download_timed_out = self._wait_downloads(timeout=300)

        # 清理 DownloadManager 资源（与 GUI shutdown 对齐）
        if self._dl_manager:
            self._dl_manager.stop_all()

        # 超时检测：标记仍在下载中的项目（与 CLI download 命令和 SDK download_video 对齐）
        if download_timed_out:
            video_status = _video_status_enum()
            for item in self.videos.values():
                if item.status in (video_status.DOWNLOADING.label, video_status.PENDING.label):
                    item.status = video_status.TIMED_OUT.label
                    item.meta["download_error"] = "下载超时 (300s)"

        self._reconcile_download_states()

        elapsed = round(time.time() - start, 2)
        self._log(f"spider 已结束, 耗时 {elapsed}s, 收集到 {len(self.videos)} 个项目, 二次选择 {self.selection_count} 次")

        # 用户取消：返回 "cancelled" 状态（与 SKILL.md 文档对齐）
        if self._cancelled:
            self._log("用户取消操作")
            return self._build_result("cancelled", start, "用户取消")

        return self._build_result("ok" if not self.error else "error", start)

    def _wait_downloads(self, timeout: float = 300) -> bool:
        """等待所有下载任务完成。

        GUI 中下载是异步的（用户可以看到进度条实时更新），
        CLI 中需要等所有下载结束才能返回最终结果。

        Returns:
            bool: 是否超时 (True=超时, False=正常完成)
        """
        if not self._dl_manager:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            counter = getattr(self._dl_manager, "pending_work_counts", None)
            counts = counter() if callable(counter) else None
            if isinstance(counts, (tuple, list)) and len(counts) == 2:
                active, queued = counts
            else:
                active = len(getattr(self._dl_manager, "workers", []))
                queued = self._dl_manager.queue.qsize()
            if active == 0 and queued == 0:
                return False
            self._emit_download_heartbeat()
            time.sleep(0.5)
        return True

    def _reconcile_download_states(self) -> None:
        """在 CLI 汇总前按真实文件落盘结果兜底校正状态。

        部分下载器在进程退出窗口期可能先落盘再迟到地发状态信号；CLI 最终
        JSON 以磁盘上非空文件为准，避免用户看到“失败但文件已完成”的结果。
        """
        video_status = _video_status_enum()
        for item in self.videos.values():
            if item.status in (
                video_status.COMPLETED.label,
                video_status.FAILED.label,
                video_status.TIMED_OUT.label,
            ):
                continue
            local_path = getattr(item, "local_path", "") or ""
            if local_path and os.path.exists(local_path):
                try:
                    if os.path.getsize(local_path) > 0:
                        item.status = video_status.COMPLETED.label
                        item.progress = 100
                except OSError:
                    pass

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

        result = {
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
        return result

    def stop(self) -> None:
        """中途停止爬虫（与 GUI on_stop_crawl 对齐）。"""
        self._cancelled = True
        if self._spider and self._spider.isRunning():
            self._spider_session.stop_session(self._spider)
        if self._dl_manager:
            self._dl_manager.stop_all()

def run_search(
    source: str,
    keyword: str,
    save_dir: str = "downloads",
    selection_strategy=None,
    download: bool = True,
    timeout: float | None = None,
    **config,
) -> dict:
    """便捷函数：启动一次爬虫并返回结果。

    与 UcrawlSDK.search() 参数对齐：支持 timeout（整体超时秒数）。

    Example:
        result = run_search("douyin", "测试关键词", max_items=20, save_dir="downloads")
        result = run_search("douyin", "测试关键词", timeout=60)
    """
    runner = CLIRunner(
        source=source,
        keyword=keyword,
        save_dir=save_dir,
        selection_strategy=selection_strategy,
        config=config,
        download=download,
        timeout=timeout,
    )
    return runner.run()
