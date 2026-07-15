"""CLI 爬取、选择与下载的同步执行运行时。

``CLIRunner`` 通过 ``SpiderSession`` 创建并绑定 spider，把二次选择桥接为同步
策略，并可把发现的项目交给 ``DownloadManager``。与事件循环驱动的桌面端不
同，``run()`` 会等待 spider 和可选下载阶段结束，再返回包含最终项目状态、
日志、选择次数与耗时的结果字典。
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
    """在无窗口环境中执行一次可等待、可取消的爬取任务。"""

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

        参数：
            source: 平台 ID (douyin/bilibili/kuaishou/missav)
            keyword: 搜索关键词 / 链接 / 用户 ID
            save_dir: 保存目录
            selection_strategy: 二次选择策略 (默认 AutoSelection)
            config: 平台特定参数
            verbose: 是否输出详细信息
            log_to_stderr: spider 日志是否输出到 stderr
            timeout: 超时秒数 (None=无限)
            download: 是否把发现的项目加入下载队列；False 时只收集结果
        """
        self.source = source
        # 入口边界统一去除关键词两端空白，避免插件收到空白伪关键词。
        self.keyword = keyword.strip() if isinstance(keyword, str) else keyword
        self.save_dir = save_dir
        self.config = dict(config or {})
        self.selection_strategy = selection_strategy or AutoSelection()
        self.verbose = verbose
        self.log_to_stderr = log_to_stderr
        self.timeout = timeout
        self.download = download

        # 这些状态共同构成 run() 的返回快照。
        self.videos: dict[str, Any] = {}    # 以视频 ID 建立到 `VideoItem` 的索引。
        self.logs: list[str] = []           # spider 日志
        self.selection_count: int = 0       # ask_user_selection 调用次数
        self.error: str | None = None
        self.finished: bool = False
        self._spider = None
        self._dl_manager = None
        self._spider_session = SpiderSession()
        self._cancelled: bool = False       # 选择或 stop() 触发的取消状态
        self._progress_logged_pct: dict[str, int] = {}
        self._last_download_heartbeat_at: float = 0.0

    def _log(self, msg: str) -> None:
        if self.verbose:
            sys.stderr.write(f"[CLI] {msg}\n")
            sys.stderr.flush()

    def _debug_log(self, action: str, message: str, status_code: str,
                   level: str | None = None, details: dict | None = None) -> None:
        """尽力写入共享结构化日志；诊断设施不可用时不影响任务。"""
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
            pass  # 诊断日志不是 CLI 执行成功的前置条件。

    def _on_log(self, msg: str) -> None:
        """缓存 spider 日志，并按配置实时转发到 stderr。"""
        self.logs.append(str(msg))
        if self.log_to_stderr:
            sys.stderr.write(f"{msg}\n")
            sys.stderr.flush()

    def _on_item_found(self, item) -> None:
        """记录单个发现项，并按 ``download`` 决定是否立即入队。

        只收集时使用“已收集”状态，避免把没有下载计划的项目展示为等待下载。
        """
        if self.download:
            self._prepare_pending_item(item)
        else:
            item.status = "📋 已收集"
            item.progress = 0
        self.videos[item.id] = item

        if self.download and self._dl_manager:
            # 发现回调直接入队，确保 run() 等待的是本次任务产生的全部下载。
            self._dl_manager.add_task(item, self.save_dir)

        # 结构化事件供各前端使用同一条诊断记录。
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
        """处理仍通过信号发出的选择请求，并把索引恢复给 spider。

        正常路径已把 ``ask_user_selection`` 替换为同步策略；该回调保留给未使用
        替换路径的插件。
        """
        self._do_select_and_resume(items)

    def _do_select_and_resume(self, items: list) -> None:
        _prompt, indices = self._run_selection(items, strategy=self.selection_strategy)

        # resume_from_ui 是 spider 对信号式选择的恢复协议。
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
        """记录 spider 完成并释放活动引用。"""
        self.finished = True
        self._spider = None  # 完成后不保留线程对象引用。
        self._log("✅ 爬虫任务结束")
        # 完成事件与启动事件共享同一结构化日志通道。
        self._debug_log("crawl_finished", "CLI 爬虫任务结束", "CLI_CRAWL_FINISH")

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

    def _make_ask_user_selection(self):
        """生成同步版的 ask_user_selection 闭包。

        spider 线程直接调用 ``selection_strategy.select()`` 并取得索引，不依赖 Qt
        信号或事件循环。取消结果会同步记录到 runner，供 ``run()`` 返回
        ``cancelled``。
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

    def _patch_spider(self, spider) -> None:
        """只负责 monkey-patch 选择行为，信号绑定统一交给 SpiderSession。"""
        from types import MethodType
        # 仅替换交互边界；生命周期与信号连接仍由 SpiderSession 管理。
        spider.ask_user_selection = MethodType(self._make_ask_user_selection(), spider)

    def _connect_download_signals(self):
        """绑定用于维护返回快照的下载状态回调。"""
        if self._dl_manager:
            self._dl_manager.task_started.connect(self._on_task_started)
            self._dl_manager.task_progress.connect(self._on_task_progress)
            self._dl_manager.task_finished.connect(self._on_task_finished)
            self._dl_manager.task_error.connect(self._on_task_error)

    def _wait_spider(self, spider, timeout: float | None = None) -> bool:
        """等待 spider 结束。

        返回：
            bool: True=正常结束，False=超时
        """
        deadline = time.time() + timeout if timeout is not None else None
        while True:
            try:
                running = spider.isRunning()
            except Exception:
                # 非 QThread 兼容实现可只暴露原生 wait()。
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

    def run(self) -> dict:
        """执行任务并返回稳定的 CLI 结果字典。

        ``status`` 为 ``ok``、``error``、``timeout`` 或 ``cancelled``。返回值还含
        source、keyword、save_dir、items、logs、selection_count、elapsed 与
        error。``timeout`` 限制 spider 阶段；下载模式会在 spider 结束后继续等待
        队列清空，并把仍未完成的项目标记为超时。
        """
        start = time.time()

        # 先解析插件并创建 spider；构造失败以结构化错误返回。
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
            # 创建异常属于调用结果，不泄漏为未分类的线程启动异常。
            self._log(f"❌ 创建爬虫失败: {exc}")
            return {
                "status": "error",
                "error": f"创建爬虫失败: {exc}",
            }
        self._spider = spider

        # 下载管理器必须在绑定发现回调前就绪，避免早到项目无法入队。
        if self.download:
            from app.config import cfg
            from app.core.download_manager import DownloadManager
            self._dl_manager = DownloadManager(
                max_concurrent=cfg.get("download", "max_concurrent", 3)
            )
            self._connect_download_signals()

        # SpiderSession 统一绑定生命周期回调，并注入同步选择边界。
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

        # 所有回调安装完成后再启动 spider。
        self._log(f"🟢 启动任务 | 模式: {plugin.name} | 关键词: {self.keyword}")
        # 启动记录包含可诊断的活动配置摘要。
        self._debug_log("start_crawl", "CLI 启动爬虫任务", "CLI_CRAWL_START",
                         details={
                             "keyword": self.keyword,
                             "source_id": self.source,
                             "plugin_name": plugin.name,
                             "active_config": self._summarize_active_config(self.config),
                         })
        spider.start()

        # ``timeout`` 只约束 spider；超时后给已入队下载一个有限清理窗口。
        if self.timeout is not None:
            finished_in_time = self._wait_spider(spider, timeout=self.timeout)
            if not finished_in_time:
                self._log(f"spider 超过 {self.timeout}s 未完成，强制停止")
                spider.stop()
                spider.wait(5000)
                # 给超时前已入队的下载最多 30 秒完成。
                dl_timed_out = self._wait_downloads(timeout=30)
                # 清理仍在运行的下载线程，避免 run() 返回后遗留后台任务。
                if self._dl_manager:
                    self._dl_manager.stop_all()
                # 调用方需要从项目状态识别未在清理窗口内完成的下载。
                if dl_timed_out:
                    video_status = _video_status_enum()
                    for item in self.videos.values():
                        if item.status in (video_status.DOWNLOADING.label, video_status.PENDING.label):
                            item.status = video_status.TIMED_OUT.label
                            item.meta["download_error"] = "下载超时 (30s)"
                # 超时返回前释放 spider 引用。
                self._spider = None
                return self._build_result("timeout", start, f"timeout after {self.timeout}s")
        else:
            self._wait_spider(spider)

        # CLI 返回最终项目快照，因此下载模式需等待队列，最长 300 秒。
        download_timed_out = False
        if self.download and self._dl_manager:
            download_timed_out = self._wait_downloads(timeout=300)

        # 无论队列是否超时，都在构造结果前停止下载管理器。
        if self._dl_manager:
            self._dl_manager.stop_all()

        # 300 秒后仍处于等待或下载中的项目明确标记为超时。
        if download_timed_out:
            video_status = _video_status_enum()
            for item in self.videos.values():
                if item.status in (video_status.DOWNLOADING.label, video_status.PENDING.label):
                    item.status = video_status.TIMED_OUT.label
                    item.meta["download_error"] = "下载超时 (300s)"

        self._reconcile_download_states()

        elapsed = round(time.time() - start, 2)
        self._log(f"spider 已结束, 耗时 {elapsed}s, 收集到 {len(self.videos)} 个项目, 二次选择 {self.selection_count} 次")

        # 取消是独立终态，不与一般错误合并。
        if self._cancelled:
            self._log("用户取消操作")
            return self._build_result("cancelled", start, "用户取消")

        return self._build_result("ok" if not self.error else "error", start)

    def _wait_downloads(self, timeout: float = 300) -> bool:
        """等待所有下载任务完成。

        GUI 中下载是异步的（用户可以看到进度条实时更新），
        CLI 中需要等所有下载结束才能返回最终结果。

        返回：
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
        """构建包含最终 status、progress 与 local_path 的结果快照。"""
        elapsed = round(time.time() - start_time, 2)

        # 对外结果保持列表形状，内部仍按 video_id 去重。
        items = []
        for item in self.videos.values():
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
        """标记取消并停止当前 spider 与下载管理器。"""
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

    ``timeout`` 是整次 spider 阶段的上限，并原样传给 ``CLIRunner``。

    示例：
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
