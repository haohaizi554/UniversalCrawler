"""控制器直连型 Web 路由服务。"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Callable

from fastapi import HTTPException, Request

from app.web.api_result import error_result
from app.web.logging_utils import log_web_event

_VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def require_valid_video_id(video_id: str) -> str:
    if not isinstance(video_id, str) or not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise HTTPException(status_code=400, detail="invalid video_id")
    return video_id


class WebControllerRouteService:
    """封装调试事件触发与视频改名/删除等控制器适配逻辑。"""

    def __init__(self, *, get_request_context: Callable[[Request], Any]) -> None:
        self._get_request_context = get_request_context

    async def trigger_select(self, request: Request) -> dict:
        if os.getenv("UCRAWL_DEBUG_ROUTES", "0") != "1":
            return error_result("debug route disabled", http_status=404)
        items = [
            {"title": "测试视频 1: 演示 modal 弹窗是否正常显示", "index": 0},
            {"title": "测试视频 2: 检查 z-index 和 position:fixed", "index": 1},
            {"title": "测试视频 3: 验证全选/反选/取消/开始下载按钮", "index": 2},
            {"title": "测试视频 4: 与 GUI SelectionDialog 视觉对照", "index": 3},
        ]
        loop = asyncio.get_running_loop()
        context = self._get_request_context(request)
        loop.call_soon(lambda: loop.create_task(context.send("select_tasks", {"items": items})))
        log_web_event(
            "WebControllerRouteService",
            "trigger_select",
            "已调度 select_tasks 测试事件",
            details={"items_sent": len(items)},
        )
        return {"status": "ok", "items_sent": len(items)}

    async def delete_video(self, request: Request, video_id: str) -> dict:
        context = self._get_request_context(request)
        try:
            video_id = require_valid_video_id(video_id)
        except HTTPException:
            return error_result("invalid video_id", http_status=400)
        await context.controller.async_delete_video(video_id, context.approved_roots)
        return {"status": "ok"}

    async def rename_video(self, request: Request, body: dict) -> dict:
        context = self._get_request_context(request)
        video_id = body.get("video_id", "")
        new_title = body.get("new_title", "")
        if not isinstance(video_id, str) or not isinstance(new_title, str):
            return error_result("video_id 和 new_title 必须是字符串")
        try:
            video_id = require_valid_video_id(video_id)
        except HTTPException:
            return error_result("invalid video_id", http_status=400)
        return await context.controller.async_rename_video(video_id, new_title, context.approved_roots)
