"""WebUI 工作流服务：统一 REST / WebSocket 的业务执行逻辑。"""

from __future__ import annotations

import asyncio
import time
from time import monotonic as _monotonic
from typing import Any, Callable, Coroutine

from app.core.events import (
    build_task_error_event,
    build_task_finished_event,
    build_task_started_event,
    build_video_state_event,
)
from app.core.state import VideoStatus
from app.models.video_item import VideoItem
from app.debug_logger import debug_logger
from shared.interactive_selection import InteractiveTTYSelection
from shared.pipe_selection import PipeSelection
from shared.runtime_options import (
    build_missav_proxy_url,
    get_platform_defaults,
    infer_content_type,
    infer_content_type_from_url,
    merge_convenience_params,
    validate_config_types,
    validate_direct_download_url,
)
from shared.runtime_adapters import build_sdk
from shared.selection_runtime import RuleSelection

BroadcastFn = Callable[[str, Any], Coroutine[Any, Any, Any]]

def build_selection_strategy(selection_dict: dict | None):
    """从 Web 端 `selection` 参数构建 SelectionStrategy 实例。"""
    if not selection_dict:
        return RuleSelection(all_items=True)

    strategy = selection_dict.get("strategy", "all")
    if strategy == "all":
        return RuleSelection(all_items=True)
    if strategy == "first":
        return RuleSelection(first=True)
    if strategy == "last":
        return RuleSelection(last=True)
    if strategy == "rule":
        select_val = selection_dict.get("select")
        exclude_val = selection_dict.get("exclude")
        if select_val is not None and not isinstance(select_val, str):
            return None
        if exclude_val is not None and not isinstance(exclude_val, str):
            return None
        return RuleSelection(
            select=select_val,
            exclude=exclude_val,
            all_items=selection_dict.get("all_items", False),
            first=selection_dict.get("first", False),
            last=selection_dict.get("last", False),
        )
    if strategy == "preload":
        choices = selection_dict.get("choices", [])
        if not isinstance(choices, list):
            return None
        for round_choices in choices:
            if not isinstance(round_choices, list):
                return None
        return PipeSelection(preloaded_choices=choices)
    if strategy == "interactive":
        return InteractiveTTYSelection()
    if strategy == "pipe":
        return PipeSelection()
    return None

def merge_default_config(source: str, user_config: dict) -> dict:
    """合并平台默认配置与用户配置。"""
    merged = get_platform_defaults(source)
    merged.update({k: v for k, v in user_config.items() if v is not None})
    if source == "missav" and "proxy" in merged and merged["proxy"] is not None:
        merged["proxy"] = build_missav_proxy_url(merged["proxy"])
    return merged

class WebWorkflowService:
    """统一 WebUI REST / WS 工作流，减少路由层重复。"""

    def __init__(self, controller, broadcast: BroadcastFn):
        self.controller = controller
        self.broadcast = broadcast
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._pending_progress_tasks: dict[str, asyncio.Task[Any]] = {}
        self._progress_throttle_seconds = 0.25
        self._last_progress_emit: dict[str, tuple[int, float]] = {}
        self._progress_broadcast_generation: dict[str, int] = {}

    async def _emit_log(self, message: str) -> None:
        await self.broadcast("log", {"message": message})

    async def _error(
        self,
        message: str,
        *,
        log_error: bool = False,
        crawl_state_false: bool = False,
    ) -> dict:
        if log_error:
            await self._emit_log(f"❌ {message}" if not message.startswith(("❌", "⚠️")) else message)
        if crawl_state_false:
            await self.broadcast("crawl_state", {"is_running": False})
        return {"status": "error", "error": message}

    async def start_crawl(self, payload: dict, *, log_error: bool) -> dict:
        source = payload.get("source", "")
        keyword = payload.get("keyword", "")
        if "download" in payload:
            return await self._error(
                "此端点始终触发下载，不支持 download 参数。如需只搜索不下载，请使用 POST /api/search 并传 download: false",
                log_error=log_error,
                crawl_state_false=True,
            )
        if not isinstance(source, str) or not isinstance(keyword, str):
            return await self._error("source 和 keyword 必须是字符串", log_error=log_error, crawl_state_false=True)
        keyword = keyword.strip()
        if not source or not keyword:
            return await self._error("source 和 keyword 为必填参数", log_error=log_error, crawl_state_false=True)

        from app.core.plugin_registry import registry

        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return await self._error(f"无效平台: {source}。支持: {valid_ids}", log_error=log_error, crawl_state_false=True)

        has_active_spider = getattr(self.controller, "_has_active_spider", None)
        spider_running = has_active_spider() if callable(has_active_spider) else bool(
            getattr(self.controller, "current_spider", None)
            and self.controller.current_spider.isRunning()
        )
        if spider_running:
            message = "当前已有任务在运行，请先停止或等待结束"
            if log_error:
                await self._emit_log(f"⚠️ {message}")
            return {"status": "error", "error": message}

        user_config = payload.get("config", {})
        if not isinstance(user_config, dict):
            return await self._error("config 必须是 JSON 对象", log_error=log_error, crawl_state_false=True)
        config_err = validate_config_types(user_config)
        if config_err:
            return await self._error(config_err, log_error=log_error, crawl_state_false=True)

        selection_dict = payload.get("selection")
        if selection_dict is not None and not isinstance(selection_dict, dict):
            return await self._error("selection 必须是 JSON 对象或 null", log_error=log_error, crawl_state_false=True)
        if selection_dict is not None:
            strategy = build_selection_strategy(selection_dict)
            if strategy is None:
                valid_strategies = ["all", "first", "last", "rule", "preload", "interactive", "pipe"]
                return await self._error(f"无效选择策略。支持: {valid_strategies}", log_error=log_error, crawl_state_false=True)
            self.controller._pending_selection_strategy = strategy
        else:
            self.controller._pending_selection_strategy = None

        merged_config = merge_default_config(source, user_config)
        try:
            merge_convenience_params(payload, merged_config, source)
        except ValueError as exc:
            return await self._error(str(exc), log_error=log_error, crawl_state_false=True)

        old_save_dir = self.controller.current_save_dir
        save_dir = payload.get("save_dir")
        if save_dir is not None and not isinstance(save_dir, str):
            return await self._error("save_dir 必须是字符串或 null", log_error=log_error, crawl_state_false=True)
        if save_dir:
            self.controller.current_save_dir = save_dir

        try:
            self.controller.start_crawl(source, keyword, merged_config)
        except Exception as exc:
            self.controller.current_save_dir = old_save_dir
            self.controller._pending_selection_strategy = None
            return await self._error(f"启动爬虫异常: {exc}", log_error=log_error, crawl_state_false=True)
        return {"status": "ok"}

    async def select_tasks(self, payload: dict, *, log_error: bool) -> dict:
        has_active_spider = getattr(self.controller, "_has_active_spider", None)
        spider_running = has_active_spider() if callable(has_active_spider) else bool(
            getattr(self.controller, "current_spider", None)
            and self.controller.current_spider.isRunning()
        )
        if not spider_running:
            return await self._error("当前没有正在运行的爬虫，无法进行二次选择", log_error=log_error)
        indices = payload.get("indices", [])
        if indices is None:
            self.controller.resume_spider_selection(None)
            return {"status": "ok"}
        if not isinstance(indices, list):
            return await self._error("indices 必须是整数数组", log_error=log_error)
        try:
            normalized = [int(i) for i in indices]
        except (TypeError, ValueError):
            return await self._error("indices 必须是整数数组", log_error=log_error)
        self.controller.resume_spider_selection(normalized)
        return {"status": "ok"}

    def _create_pending_item(self, url: str, source: str, title: str) -> VideoItem:
        item = VideoItem(url=url, title=title, source=source, status=VideoStatus.PENDING.label, progress=0)
        prefix = {"douyin": "dy", "bilibili": "bilibili", "kuaishou": "ks", "missav": "missav", "xiaohongshu": "xhs"}.get(source, source)
        item.meta["trace_id"] = debug_logger.new_trace_id(f"{prefix}_dl")
        pre_ct = infer_content_type_from_url(url)
        if pre_ct:
            item.meta["content_type"] = pre_ct
        return item

    def _schedule_broadcast(self, loop: asyncio.AbstractEventLoop, event_type: str, data: dict) -> None:
        def _schedule() -> None:
            task = loop.create_task(self.broadcast(event_type, data))
            self._pending_tasks.add(task)

            def _discard(done_task: asyncio.Task[Any]) -> None:
                self._pending_tasks.discard(done_task)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception("Web workflow broadcast failed")

            task.add_done_callback(_discard)

        loop.call_soon_threadsafe(_schedule)

    def cancel_pending_broadcasts(self) -> None:
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        for task in list(self._pending_progress_tasks.values()):
            task.cancel()
        self._pending_progress_tasks.clear()
        self._last_progress_emit.clear()
        self._progress_broadcast_generation.clear()

    def _should_emit_progress(self, video_id: str, progress: int) -> bool:
        try:
            normalized = max(0, min(100, int(progress)))
        except (TypeError, ValueError):
            return False
        # 测试只替换本模块的时钟绑定，避免污染 asyncio 共用的全局单调时钟。
        now = _monotonic()
        last = self._last_progress_emit.get(video_id)
        if last is not None:
            last_progress, last_at = last
            if normalized == last_progress:
                return False
            if normalized not in {0, 100} and now - last_at < self._progress_throttle_seconds:
                return False
        self._last_progress_emit[video_id] = (normalized, now)
        return True

    def _cancel_pending_progress_broadcast(self, video_id: str) -> None:
        self._progress_broadcast_generation[video_id] = self._progress_broadcast_generation.get(video_id, 0) + 1
        task = self._pending_progress_tasks.pop(video_id, None)
        if task is not None:
            if not task.done():
                task.cancel()
            self._pending_tasks.discard(task)
        self._last_progress_emit.pop(video_id, None)

    def _schedule_progress_broadcast(
        self,
        loop: asyncio.AbstractEventLoop,
        video_id: str,
        pending_item: VideoItem,
        progress: int,
    ) -> None:
        try:
            normalized = max(0, min(100, int(progress)))
        except (TypeError, ValueError):
            return
        if not self._should_emit_progress(video_id, progress):
            return
        generation = self._progress_broadcast_generation.get(video_id, 0) + 1
        self._progress_broadcast_generation[video_id] = generation
        existing = self._pending_progress_tasks.get(video_id)
        if existing is not None and not existing.done():
            existing.cancel()
        payload = build_video_state_event(
            video_id,
            pending_item,
            requested_progress=normalized,
        ).to_payload()

        def _schedule() -> None:
            if self._progress_broadcast_generation.get(video_id, 0) != generation:
                return
            task = loop.create_task(self.broadcast("video_state_changed", payload))
            self._pending_tasks.add(task)
            self._pending_progress_tasks[video_id] = task

            def _discard(done_task: asyncio.Task[Any]) -> None:
                self._pending_tasks.discard(done_task)
                if self._pending_progress_tasks.get(video_id) is done_task:
                    self._pending_progress_tasks.pop(video_id, None)
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception("Web workflow progress broadcast failed")

            task.add_done_callback(_discard)

        loop.call_soon_threadsafe(_schedule)

    async def _broadcast_download_started(self, pending_item: VideoItem) -> None:
        store_video = getattr(self.controller, "_store_video_item", None)
        if callable(store_video):
            store_video(pending_item)
        else:
            self.controller.videos[pending_item.id] = pending_item
        await self.broadcast("item_found", self.controller._video_item_to_dict(pending_item))
        pending_item.status = VideoStatus.DOWNLOADING.label
        await self.broadcast(
            "task_started",
            build_task_started_event(pending_item.id, pending_item).to_payload(),
        )
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=0).to_payload(),
        )

    async def _broadcast_download_error(self, pending_item: VideoItem, error_msg: str) -> None:
        self._cancel_pending_progress_broadcast(pending_item.id)
        if "超时" in error_msg:
            pending_item.status = VideoStatus.TIMED_OUT.label
        else:
            pending_item.status = VideoStatus.FAILED.label
        pending_item.progress = 0
        if pending_item.meta is None:
            pending_item.meta = {}
        pending_item.meta["download_error"] = error_msg
        await self.broadcast(
            "task_error",
            build_task_error_event(pending_item.id, pending_item, error_msg).to_payload(),
        )
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=0).to_payload(),
        )
        await self._emit_log(f"❌ 下载失败: {error_msg}")

    async def _broadcast_download_success(self, pending_item: VideoItem, result: dict) -> dict:
        self._cancel_pending_progress_broadcast(pending_item.id)
        pending_item.status = VideoStatus.COMPLETED.label
        pending_item.progress = 100
        local_path = result.get("local_path", "")
        if local_path:
            pending_item.local_path = local_path
        pending_item.title = result.get("title", pending_item.title)
        if pending_item.meta is None:
            pending_item.meta = {}
        content_type = result.get("content_type", "")
        if not content_type and local_path:
            content_type = infer_content_type(local_path)
            result["content_type"] = content_type
        if content_type:
            pending_item.meta["content_type"] = content_type
        pending_item.meta.update(result.get("meta", {}))
        result["video_id"] = pending_item.id
        await self.broadcast(
            "task_finished",
            build_task_finished_event(pending_item.id, pending_item).to_payload(),
        )
        await self.broadcast(
            "video_state_changed",
            build_video_state_event(pending_item.id, pending_item, requested_progress=100).to_payload(),
        )
        await self._emit_log(f"✅ 下载完成: {pending_item.title}")
        return result

    async def direct_download(self, payload: dict, *, log_error: bool) -> dict:
        start_at = time.time()
        url = payload.get("url", "")
        source = payload.get("source", "")
        title = payload.get("title")
        if title is not None and not isinstance(title, str):
            return await self._error("title 必须是字符串", log_error=log_error)
        timeout = payload.get("timeout", 300)
        user_config = payload.get("config", {})

        if not isinstance(url, str) or not isinstance(source, str):
            return await self._error("url 和 source 必须是字符串", log_error=log_error)
        if not url or not source:
            return await self._error("url 和 source 为必填参数", log_error=log_error)
        url = url.strip()
        url_error = validate_direct_download_url(url)
        if url_error:
            return await self._error(url_error, log_error=log_error)
        title = title or url

        from app.core.plugin_registry import registry

        plugin = registry.get_plugin(source)
        if not plugin:
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return await self._error(f"无效平台: {source}。支持: {valid_ids}", log_error=log_error)

        save_dir = payload.get("save_dir")
        if save_dir is not None and not isinstance(save_dir, str):
            return await self._error("save_dir 必须是字符串或 null", log_error=log_error)
        if not isinstance(user_config, dict):
            return await self._error("config 必须是 JSON 对象", log_error=log_error)
        config_err = validate_config_types(user_config)
        if config_err:
            return await self._error(config_err, log_error=log_error)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            return await self._error("timeout 必须是数字", log_error=log_error)
        if timeout <= 0:
            return await self._error("timeout 必须大于 0", log_error=log_error)

        effective_save_dir = save_dir or self.controller.current_save_dir
        merged_config = get_platform_defaults(source)
        merged_config.update({k: v for k, v in user_config.items() if v is not None})
        try:
            config_payload = {key: value for key, value in payload.items() if key != "timeout"}
            merge_convenience_params(config_payload, merged_config, source)
        except ValueError as exc:
            return await self._error(str(exc), log_error=log_error)
        user_config = merged_config

        pending_item = self._create_pending_item(url, source, title or url)
        await self._broadcast_download_started(pending_item)

        sdk = build_sdk(save_dir=effective_save_dir)
        loop = asyncio.get_running_loop()
        try:
            def on_download_progress(pct: int) -> None:
                pending_item.progress = pct
                self._schedule_progress_broadcast(loop, pending_item.id, pending_item, pct)

            result = await loop.run_in_executor(
                None,
                lambda: sdk.download_video(
                    url=url,
                    source=source,
                    title=title,
                    save_dir=effective_save_dir,
                    timeout=timeout,
                    config=user_config,
                    progress_callback=on_download_progress,
                    network_policy="public",
                ),
            )
        except (TypeError, ValueError) as exc:
            await self._broadcast_download_error(pending_item, str(exc))
            return {
                "status": "error",
                "error": str(exc),
                "video_id": pending_item.id,
                "url": url,
                "source": source,
                "title": title or url,
                "save_dir": effective_save_dir,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "meta": {"download_error": str(exc)},
                "elapsed": round(time.time() - start_at, 2),
            }
        except Exception as exc:
            error_msg = f"下载失败: {exc}"
            await self._broadcast_download_error(pending_item, error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "video_id": pending_item.id,
                "url": url,
                "source": source,
                "title": title or url,
                "save_dir": effective_save_dir,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "meta": {"download_error": error_msg},
                "elapsed": round(time.time() - start_at, 2),
            }
        finally:
            try:
                sdk.close()
            except (RuntimeError, OSError, AttributeError) as exc:
                debug_logger.log_exception("WebWorkflowService", "close_sdk", exc)

        if result.get("status") == "ok":
            return await self._broadcast_download_success(pending_item, result)

        error_msg = result.get("error", "下载失败")
        if result.get("local_path"):
            pending_item.local_path = result["local_path"]
        if result.get("title"):
            pending_item.title = result["title"]
        if isinstance(result.get("meta"), dict):
            pending_item.meta.update(result["meta"])
        result["video_id"] = pending_item.id
        await self._broadcast_download_error(pending_item, error_msg)
        return result
