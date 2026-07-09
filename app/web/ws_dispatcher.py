"""WebSocket 消息分发层。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable

from app.config import cfg
from app.web.controller_config_service import WebControllerConfigService
from app.web.logging_utils import log_web_exception
from app.web.session_runtime import WebSessionContext

Handler = Callable[[dict[str, Any], WebSessionContext], Awaitable[None]]
MAX_SCAN_LIMIT = 5000


async def _run_controller_worker_call(func: Callable[..., Any], *args: Any) -> Any:
    """把同步 controller/config 调用丢到线程池，避免阻塞 WebSocket receive loop。"""
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


class WebSocketMessageDispatcher:
    """集中处理 WebSocket 协议消息，避免 server.py 承担业务分发职责。"""

    def __init__(self) -> None:
        self._config_service = WebControllerConfigService()
        self._handlers: dict[str, Handler] = {
            "start_crawl": self._handle_start_crawl,
            "stop_crawl": self._handle_stop_crawl,
            "select_tasks": self._handle_select_tasks,
            "scan_dir": self._handle_scan_dir,
            "change_dir": self._handle_change_dir,
            "change_theme": self._handle_change_theme,
            "change_source": self._handle_change_source,
            "save_config": self._handle_save_config,
            "delete_video": self._handle_delete_video,
            "rename_video": self._handle_rename_video,
            "download": self._handle_download,
            "frontend_action": self._handle_frontend_action,
        }

    async def handle(self, msg: dict, context: WebSessionContext) -> None:
        """按消息类型分发到具体处理器。"""
        msg_type = msg.get("type", "")
        data = msg.get("data", {}) or {}
        handler = self._handlers.get(msg_type)
        if handler is None:
            await context.send("error", {"message": f"unknown message type: {msg_type or '<empty>'}"})
            return

        try:
            await handler(data, context)
        except Exception as exc:
            log_web_exception(
                "WebSocketMessageDispatcher",
                "handle",
                exc,
                context={"message_type": msg_type},
            )
            try:
                await context.send("log", {"message": f"❌ 处理 {msg_type} 失败: {exc}"})
            except Exception as send_exc:
                log_web_exception(
                    "WebSocketMessageDispatcher",
                    "send_error_feedback",
                    send_exc,
                    context={"message_type": msg_type},
                )

    async def _emit_log(self, context: WebSessionContext, message: str) -> None:
        await context.send("log", {"message": message})

    @staticmethod
    def _set_config_values(section: str, values: dict[str, Any]) -> None:
        set_many = getattr(cfg, "set_many", None)
        if callable(set_many):
            set_many(section, values)
            return
        for key, value in values.items():
            cfg.set(section, key, value)

    @staticmethod
    def _set_config_value(section: str, key: str, value: Any) -> None:
        cfg.set(section, key, value)

    async def _normalize_authorized_save_dir(
        self,
        data: dict[str, Any],
        context: WebSessionContext,
    ) -> dict[str, Any] | None:
        """校验客户端传入目录必须位于会话授权根内，防止 Web 端任意路径写入。"""
        save_dir = data.get("save_dir")
        if save_dir is None:
            return data
        if not isinstance(save_dir, str):
            await self._emit_log(context, "❌ save_dir 必须是字符串")
            return None
        try:
            normalized = context.require_directory(save_dir)
        except PermissionError as exc:
            await self._emit_log(context, f"❌ {exc}")
            return None
        payload = dict(data)
        payload["save_dir"] = normalized
        return payload

    async def _handle_start_crawl(self, data: dict[str, Any], context: WebSessionContext) -> None:
        payload = await self._normalize_authorized_save_dir(data, context)
        if payload is None:
            return
        await context.workflow.start_crawl(payload, log_error=True)

    async def _handle_stop_crawl(self, data: dict[str, Any], context: WebSessionContext) -> None:
        del data
        await _run_controller_worker_call(context.controller.stop_crawl)

    async def _handle_select_tasks(self, data: dict[str, Any], context: WebSessionContext) -> None:
        await context.workflow.select_tasks(data, log_error=True)

    async def _handle_scan_dir(self, data: dict[str, Any], context: WebSessionContext) -> None:
        """处理目录扫描请求；scan_limit 在入口层限幅，避免一次扫描拖垮事件循环。"""
        directory = data.get("directory")
        if directory is not None and not isinstance(directory, str):
            await self._emit_log(context, "❌ directory 必须是字符串")
            return

        scan_limit = data.get("scan_limit")
        if scan_limit is not None:
            if not isinstance(scan_limit, int):
                await self._emit_log(context, "❌ scan_limit 必须是整数")
                return
            if scan_limit <= 0:
                await self._emit_log(context, "❌ scan_limit 必须大于 0")
                return
            if scan_limit > MAX_SCAN_LIMIT:
                await self._emit_log(context, f"❌ scan_limit 不能大于 {MAX_SCAN_LIMIT}")
                return

        try:
            normalized_directory = context.require_directory(directory) if directory else None
        except PermissionError as exc:
            await self._emit_log(context, f"❌ {exc}")
            return

        await context.controller.async_scan_local_dir(normalized_directory, scan_limit=scan_limit)

    async def _handle_change_dir(self, data: dict[str, Any], context: WebSessionContext) -> None:
        directory = data.get("directory", "")
        if not directory:
            await self._emit_log(context, "❌ 目录路径不能为空")
            return
        if not isinstance(directory, str):
            await self._emit_log(context, "❌ directory 必须是字符串")
            return

        try:
            directory = context.require_directory(directory)
        except PermissionError as exc:
            await self._emit_log(context, f"❌ {exc}")
            return

        await context.controller.async_change_dir(directory)

    async def _handle_change_theme(self, data: dict[str, Any], context: WebSessionContext) -> None:
        is_dark = data.get("dark_theme", True)
        if not isinstance(is_dark, bool):
            await self._emit_log(context, "❌ dark_theme 必须是布尔值")
            return

        theme_values = {"theme": "dark" if is_dark else "light", "dark_theme": is_dark}
        await _run_controller_worker_call(self._set_config_values, "common", theme_values)

    async def _handle_change_source(self, data: dict[str, Any], context: WebSessionContext) -> None:
        new_source = data.get("source", "")
        if not isinstance(new_source, str):
            await self._emit_log(context, "❌ source 必须是字符串")
            return

        if new_source:
            from app.core.plugin_registry import registry

            if not registry.get_plugin(new_source):
                valid_ids = [p.id for p in registry.get_all_plugins()]
                await self._emit_log(context, f"❌ 无效平台: {new_source}。支持: {valid_ids}")
                return

        await _run_controller_worker_call(self._set_config_value, "common", "last_source", new_source)

    async def _handle_save_config(self, data: dict[str, Any], context: WebSessionContext) -> None:
        """配置保存优先走统一 frontend_action，旧控制器再退回配置服务。"""
        section = data.get("section", "")
        key = data.get("key", "")
        value = data.get("value")
        if not isinstance(section, str) or not isinstance(key, str):
            await self._emit_log(context, "❌ section 和 key 必须是字符串")
            return

        if section and key:
            handler = getattr(context.controller, "async_handle_frontend_action", None)
            if not callable(handler):
                handler = getattr(context.controller, "handle_frontend_action", None)
            if callable(handler):
                payload = {"section": section, "key": key, "value": value}
                if inspect.iscoroutinefunction(handler):
                    result = await handler("update_setting", payload)
                else:
                    result = await _run_controller_worker_call(handler, "update_setting", payload)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict) and result.get("status") != "ok":
                    await self._emit_log(context, f"❌ 保存配置失败: {result.get('message') or '未知错误'}")
                return
            error = await _run_controller_worker_call(self._config_service.update_single_config, section, key, value)
            if error:
                await self._emit_log(context, f"❌ 保存配置失败: {error}")

    async def _handle_delete_video(self, data: dict[str, Any], context: WebSessionContext) -> None:
        video_id = data.get("video_id", "")
        if not isinstance(video_id, str):
            await self._emit_log(context, "❌ video_id 必须是字符串")
            return

        await context.controller.async_delete_video(video_id, context.approved_roots)

    async def _handle_rename_video(self, data: dict[str, Any], context: WebSessionContext) -> None:
        video_id = data.get("video_id", "")
        new_title = data.get("new_title", "")
        if not isinstance(video_id, str) or not isinstance(new_title, str):
            await self._emit_log(context, "❌ video_id 和 new_title 必须是字符串")
            return

        await context.controller.async_rename_video(video_id, new_title, context.approved_roots)

    async def _handle_download(self, data: dict[str, Any], context: WebSessionContext) -> None:
        payload = await self._normalize_authorized_save_dir(data, context)
        if payload is None:
            return
        await context.workflow.direct_download(payload, log_error=True)

    async def _handle_frontend_action(self, data: dict[str, Any], context: WebSessionContext) -> None:
        """执行前端动作后尽量返回 delta，旧客户端仍可回退到完整 frontend_state。"""
        action = data.get("action", "")
        payload = data.get("payload", {}) or {}
        try:
            frontend_version = int(data.get("frontend_version") or 0)
        except (TypeError, ValueError):
            frontend_version = 0
        if not isinstance(action, str) or not isinstance(payload, dict):
            await self._emit_log(context, "❌ frontend_action 参数非法")
            return
        handler = getattr(context.controller, "async_handle_frontend_action", None)
        if not callable(handler):
            handler = getattr(context.controller, "handle_frontend_action", None)
        if not callable(handler):
            await self._emit_log(context, "❌ frontend action 不可用")
            return
        if inspect.iscoroutinefunction(handler):
            result = await handler(action, payload)
        else:
            result = await _run_controller_worker_call(handler, action, payload)
        if inspect.isawaitable(result):
            result = await result
        await context.send("frontend_action_result", result)
        delta_getter = getattr(context.controller, "get_frontend_delta", None)
        if callable(delta_getter):
            delta = await _run_controller_worker_call(delta_getter, frontend_version)
            if isinstance(delta, dict) and (
                delta.get("full")
                or int(delta.get("version") or 0) != frontend_version
            ):
                await context.send("frontend_delta", delta)
            return
        getter = getattr(context.controller, "get_frontend_state", None)
        if callable(getter):
            snapshot = await _run_controller_worker_call(getter)
            await context.send("frontend_state", snapshot)
