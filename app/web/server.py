"""FastAPI 服务器：REST API + WebSocket + 静态文件服务。"""

from __future__ import annotations

import asyncio
import inspect
import mimetypes
import os
from collections.abc import Iterator

from fastapi import FastAPI, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import cfg
from app.utils.runtime_paths import resolve_resource_file

# WebController 在 create_app() 中延迟初始化
controller = None

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _apply_no_cache_headers(response):
    for key, value in NO_CACHE_HEADERS.items():
        response.headers[key] = value
    return response


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        return _apply_no_cache_headers(response)

STATIC_DIR = resolve_resource_file("app/web/static")
UI_ICON_DIR = resolve_resource_file("UI/icon")
SESSION_COOKIE_NAME = "ucrawl_session"
SESSION_TOKEN_COOKIE_NAME = "ucrawl_session_token"
CSRF_COOKIE_NAME = "ucrawl_csrf_token"
SESSION_TOKEN_HEADER = "X-Ucrawl-Session-Token"
DEFAULT_SESSION_ID = "default"

# 确保 MIME 类型已注册
mimetypes.init()

def run_cli_search(**kwargs) -> dict:
    """Run a CLI search with normalized Web/API arguments."""
    from cli.runner import CLIRunner

    runner = CLIRunner(
        source=kwargs["source"],
        keyword=kwargs["keyword"],
        save_dir=kwargs.get("save_dir") or "downloads",
        selection_strategy=kwargs.get("selection_strategy"),
        config=kwargs.get("config") or {},
        verbose=False,
        log_to_stderr=False,
        timeout=kwargs.get("timeout"),
        download=bool(kwargs.get("download", True)),
    )
    return runner.run()

def _clear_controller_videos(active_controller) -> None:
    clear_videos = getattr(active_controller, "_clear_video_items", None)
    if callable(clear_videos):
        clear_videos()
        return
    active_controller.videos.clear()

def _store_controller_video(active_controller, item) -> None:
    store_video = getattr(active_controller, "_store_video_item", None)
    if callable(store_video):
        store_video(item)
        return
    active_controller.videos[item.id] = item


def _list_directory_payload(path: str) -> dict:
    if not os.path.exists(path):
        return {"error": "目录不存在", "path": path}

    entries = os.listdir(path)
    subdirs = []
    for name in sorted(entries, key=str.lower):
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full) and not name.startswith("."):
                subdirs.append({"name": name, "path": full})
        except PermissionError:
            continue

    parent = os.path.dirname(path) if path else ""
    drives = []
    if os.name == "nt":
        import string

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append({"name": drive, "path": drive})

    return {
        "current": path,
        "parent": parent,
        "subdirs": subdirs,
        "drives": drives,
    }


async def _run_controller_worker_call(func, *args):
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


def _media_file_info(path: str) -> tuple[str, int, str]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    file_size = os.path.getsize(path)
    content_type, _ = mimetypes.guess_type(path)
    return path, file_size, content_type or "application/octet-stream"


def _iter_file_range(path: str, start: int, chunk_size: int) -> Iterator[bytes]:
    with open(path, "rb") as file_obj:
        file_obj.seek(start)
        remaining = chunk_size
        while remaining > 0:
            read_size = min(8192, remaining)
            data = file_obj.read(read_size)
            if not data:
                break
            remaining -= len(data)
            yield data

def create_app(lifespan=None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="Universal Crawler Pro", version="3.6.17", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # 修复 BUG-186: wildcard origin 不能带 credentials
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- WebSocket 连接管理 ----

    # ---- 初始化 WebController ----

    global controller
    from app.web.controller import WebController
    from app.web.workflows import (
        WebWorkflowService,
        build_selection_strategy as _build_selection_strategy,
        merge_default_config as _merge_default_config,
        validate_config_types as _validate_config_types,
    )
    # 不在 create_app 时获取事件循环，因为 uvicorn 可能使用不同的事件循环
    # 传入 None，在首次 emit 时延迟获取正确的事件循环
    from app.web.app_composition import build_web_app_composition, publish_app_state
    from app.web.search_service import SearchRouteRuntime

    def _search_runtime_provider() -> SearchRouteRuntime:
        return SearchRouteRuntime(
            build_selection_strategy=_build_selection_strategy,
            merge_default_config=_merge_default_config,
            validate_config_types=_validate_config_types,
            run_cli_search=run_cli_search,
        )

    composition = build_web_app_composition(
        controller_factory=WebController,
        workflow_factory=WebWorkflowService,
        session_cookie_name=SESSION_COOKIE_NAME,
        session_token_cookie_name=SESSION_TOKEN_COOKIE_NAME,
        csrf_cookie_name=CSRF_COOKIE_NAME,
        session_token_header=SESSION_TOKEN_HEADER,
        default_session_id=DEFAULT_SESSION_ID,
        search_runtime_provider=_search_runtime_provider,
    )
    publish_app_state(
        app,
        composition=composition,
        session_cookie_name=SESSION_COOKIE_NAME,
        session_token_cookie_name=SESSION_TOKEN_COOKIE_NAME,
        csrf_cookie_name=CSRF_COOKIE_NAME,
        session_token_header=SESSION_TOKEN_HEADER,
    )
    manager = composition.manager
    controller = composition.default_context.controller
    workflow = composition.default_context.workflow

    @app.middleware("http")
    async def http_session_middleware(request: Request, call_next):
        return await composition.http_sessions.handle(request, call_next)

    # ---- REST API ----

    @app.get("/api/ping")
    async def ping():
        from cli import __version__
        return {"status": "ok", "version": __version__}

    @app.get("/api/platforms")
    async def get_platforms():
        return await _run_controller_worker_call(controller.get_platforms)

    @app.get("/api/config")
    async def get_config():
        return await _run_controller_worker_call(controller.get_config)

    @app.put("/api/config")
    async def update_config(updates: dict):
        # 与 GUI 设置对话框对齐：updates 必须是 dict
        if not isinstance(updates, dict):
            return {"status": "error", "error": "请求体必须是 JSON 对象"}
        handler = getattr(controller, "async_update_config", None)
        if callable(handler):
            await handler(updates)
        else:
            await _run_controller_worker_call(controller.update_config, updates)
        return {"status": "ok"}

    @app.get("/api/state")
    async def get_state():
        return await _run_controller_worker_call(controller.get_state)

    @app.get("/api/frontend/state")
    async def get_frontend_state():
        return await _run_controller_worker_call(controller.get_frontend_state)

    @app.get("/api/frontend/delta")
    async def get_frontend_delta(since_version: int = Query(default=0, ge=0)):
        getter = getattr(controller, "get_frontend_delta", None)
        if callable(getter):
            return await _run_controller_worker_call(getter, since_version)
        snapshot_getter = getattr(controller, "get_frontend_state", None)
        if callable(snapshot_getter):
            sections = await _run_controller_worker_call(snapshot_getter)
            return {
                "version": 0,
                "base_version": since_version,
                "full": True,
                "sections": sections,
            }
        return {"status": "error", "error": "frontend delta is unavailable"}

    @app.get("/api/frontend/icons")
    async def get_frontend_icons():
        return controller.get_frontend_icons()

    @app.get("/api/i18n/{language}")
    async def get_i18n_catalog(language: str):
        from app.ui.localization import SUPPORTED_LANGUAGES, TRANSLATIONS

        normalized = str(language or "").strip()
        if normalized not in SUPPORTED_LANGUAGES or normalized == "zh-CN":
            return {}
        return TRANSLATIONS.get(normalized, {})

    @app.post("/api/frontend/action")
    async def frontend_action(body: dict):
        if not isinstance(body, dict):
            return {"status": "error", "error": "请求体必须是 JSON 对象"}
        action = body.get("action", "")
        payload = body.get("payload") or {}
        try:
            frontend_version = int(body.get("frontend_version") or 0)
        except (TypeError, ValueError):
            frontend_version = 0
        if not isinstance(action, str) or not action:
            return {"status": "error", "error": "action 必须是非空字符串"}
        if not isinstance(payload, dict):
            return {"status": "error", "error": "payload 必须是 JSON 对象"}
        handler = getattr(controller, "async_handle_frontend_action", None)
        if not callable(handler):
            handler = getattr(controller, "handle_frontend_action", None)
        result = handler(action, payload)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            delta_getter = getattr(controller, "get_frontend_delta", None)
            if callable(delta_getter):
                try:
                    delta = await _run_controller_worker_call(delta_getter, frontend_version)
                except Exception:
                    delta = None
                if isinstance(delta, dict):
                    result = dict(result)
                    result["frontend_delta"] = delta
        return result

    @app.post("/api/scan")
    async def scan_directory(request: Request):
        """扫描目录并返回结果。不调用 manager.broadcast，只返回 HTTP 响应。"""
        import logging
        logger = logging.getLogger(__name__)
        try:
            body = await request.json()
        except Exception:
            body = {}

        directory = body.get("directory") or controller.current_save_dir
        if not directory:
            return {"status": "error", "error": "目录路径不能为空"}
        # 与 GUI QFileDialog 对齐：directory 必须是字符串
        if not isinstance(directory, str):
            return {"status": "error", "error": "directory 必须是字符串"}

        # 与 CLI --limit 和 SDK scan_limit 对齐：支持请求体指定 scan_limit
        scan_limit = body.get("scan_limit")
        if scan_limit is not None:
            # 与 SDK scan_directory 对齐：scan_limit 必须是整数
            if not isinstance(scan_limit, int):
                return {"status": "error", "error": "scan_limit 必须是整数"}
            # 与 SDK scan_directory 对齐：scan_limit 必须大于 0
            if scan_limit <= 0:
                return {"status": "error", "error": "scan_limit 必须大于 0"}
        if scan_limit is None:
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
            try:
                scan_limit = int(scan_limit)
            except (ValueError, TypeError):
                scan_limit = 1000

        try:
            # 与 GUI 对齐：扫描不改变 current_save_dir（只有 /api/dir/change 才改变）
            _clear_controller_videos(controller)

            result = await asyncio.get_running_loop().run_in_executor(
                None, controller.file_service.scan_directory, directory, scan_limit,
            )

            items = []
            for item in result.items:
                # 与 SDK scan_directory 一致：本地文件标记为"✅ 本地"，进度 100%
                item.status = "✅ 本地"
                item.progress = 100
                _store_controller_video(controller, item)
                try:
                    items.append(controller._video_item_to_dict(item))
                except Exception:
                    items.append({"id": item.id, "title": getattr(item, 'title', ''), "url": "", "source": "", "status": "✅ 本地", "progress": 100, "local_path": getattr(item, 'local_path', ''), "content_type": "", "meta": {}})

            msg = f"已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
            if result.truncated:
                msg = f"文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
            elif result.total_count == 0:
                msg = "该目录下没有找到视频或图片"

            return {
                "status": "ok", "directory": directory, "items": items,
                "total_count": result.total_count, "video_count": result.video_count,
                "image_count": result.image_count, "truncated": result.truncated,
                "original_count": result.original_count, "message": msg,
            }
        except Exception as exc:
            logger.error(f"[scan] 扫描失败: {exc}", exc_info=True)
            # 与成功响应对齐：错误响应也包含 directory 字段
            return {"status": "error", "error": str(exc), "directory": directory}

    @app.post("/api/search")
    async def search(body: dict):
        """同步搜索端点：使用 CLIRunner，输入输出与 CLI/SDK 完全一致。

        与 GUI ApplicationController 的行为对齐：
        1. 合并平台默认配置（get_platform_defaults，与 GUI read_*_run_options 一致）
        2. 创建 spider（同 GUI _create_spider）
        3. monkey-patch ask_user_selection（同 CLI CLIRunner）
        4. 绑定信号（同 GUI _bind_spider_signals）
        5. 等待 spider 完成 + 下载完成
        6. 返回完整结果（含最终 status/progress/local_path）

        selection 参数支持多轮二次选择（B站合集/抖音多用户等场景）：
        - {"strategy": "all"} - 全选（默认）
        - {"strategy": "first"} - 只选第一个
        - {"strategy": "last"} - 只选最后一个
        - {"strategy": "rule", "select": "0,2,5", "exclude": "1,3"} - 规则选择
        - {"strategy": "preload", "choices": [[0], [1,2]]} - 预加载多轮选择
          （choices 是二维数组，每个内层数组对应一次 ask_user_selection 调用）
        """
        import logging
        logger = logging.getLogger(__name__)

        source = body.get("source", "")
        keyword = body.get("keyword", "")
        # 与 GUI QLineEdit 对齐：source 和 keyword 必须是字符串
        if not isinstance(source, str) or not isinstance(keyword, str):
            return {"status": "error", "error": "source 和 keyword 必须是字符串"}
        # 与 GUI inp_search.text().strip() 对齐：去除前后空白
        keyword = keyword.strip()
        if not source or not keyword:
            return {"status": "error", "error": "source 和 keyword 为必填参数"}

        # 与 GUI QComboBox 和 CLI choices 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return {"status": "error", "error": f"无效平台: {source}。支持: {valid_ids}"}

        save_dir = body.get("save_dir")
        # 与 GUI QFileDialog 对齐：save_dir 必须是字符串或 null
        if save_dir is not None and not isinstance(save_dir, str):
            return {"status": "error", "error": "save_dir 必须是字符串或 null"}
        save_dir = save_dir or controller.current_save_dir
        user_config = body.get("config", {})
        # 与 GUI 对齐：Qt 控件保证 config 是 dict，REST API 需显式校验
        if not isinstance(user_config, dict):
            return {"status": "error", "error": "config 必须是 JSON 对象"}
        # 与 CLI argparse type 和 SDK _validate_config 对齐：校验已知 config 参数类型
        config_err = _validate_config_types(user_config)
        if config_err:
            return {"status": "error", "error": config_err}
        selection_dict = body.get("selection")
        # 与 GUI 对齐：selection 必须是 dict 或 null
        if selection_dict is not None and not isinstance(selection_dict, dict):
            return {"status": "error", "error": "selection 必须是 JSON 对象或 null"}
        # 与 CLI argparse choices 对齐：未知策略返回错误而非静默默认
        strategy = _build_selection_strategy(selection_dict)
        if strategy is None:
            valid_strategies = ["all", "first", "last", "rule", "preload", "interactive", "pipe"]
            return {"status": "error", "error": f"无效选择策略。支持: {valid_strategies}"}
        # 与 GUI QSpinBox 和 CLI type=float 对齐：强制转换 timeout 为 float
        # 与 SDK 对齐：支持 run_timeout 参数（优先级高于 timeout，与 SDK search() 对齐）
        timeout = body.get("run_timeout") or body.get("timeout")
        if timeout is not None:
            try:
                timeout = float(timeout)
            except (ValueError, TypeError):
                return {"status": "error", "error": "timeout/run_timeout 必须是数字"}
            # 与 SDK 对齐：timeout 必须大于 0
            if timeout <= 0:
                return {"status": "error", "error": "timeout/run_timeout 必须大于 0"}
        # 与 GUI 对齐：download 是布尔值，REST API 需强制转换（HTTP 客户端可能传字符串 "false"）
        download = body.get("download", True)
        # 与 save_dir/timeout 对齐：null 视为未提供，使用默认值 True
        if download is None:
            download = True
        if isinstance(download, str):
            download = download.lower() not in ("false", "0", "no", "off")
        elif isinstance(download, bool):
            pass  # 已经是布尔值，直接使用
        elif isinstance(download, (int, float)):
            # 与 GUI QCheckBox 对齐：不允许数字 0/1 代替布尔值，避免 bool(0)=False 误判
            return {"status": "error", "error": "download 必须是布尔值"}
        elif isinstance(download, (list, dict)):
            return {"status": "error", "error": "download 必须是布尔值"}
        else:
            return {"status": "error", "error": "download 必须是布尔值"}
        download = bool(download)

        # 合并平台默认配置 + 用户 config（与 GUI read_*_run_options 对齐）
        merged_config = _merge_default_config(source, user_config)
        # 与 CLI search 命令便捷参数对齐：支持顶层便捷参数（优先级高于 config 字典）
        from cli.defaults import merge_convenience_params
        try:
            merge_convenience_params(body, merged_config, source)
        except ValueError as e:
            return {"status": "error", "error": str(e)}

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: run_cli_search(
                    source=source,
                    keyword=keyword,
                    save_dir=save_dir,
                    selection_strategy=strategy,
                    config=merged_config,
                    timeout=timeout,
                    download=download,
                ),
            )
            return result
        except Exception as exc:
            logger.error(f"[search] 搜索失败: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc)}

    @app.post("/api/crawl/start")
    async def start_crawl(body: dict):
        return await workflow.start_crawl(body, log_error=False)

    @app.post("/api/crawl/stop")
    async def stop_crawl():
        controller.stop_crawl()
        return {"status": "ok"}

    @app.post("/api/crawl/select")
    async def select_tasks(request: Request, body: dict):
        context = composition.get_request_context(request)
        return await context.workflow.select_tasks(body, log_error=False)

    # ---- 调试: 手动触发选择弹窗 ----
    @app.post("/api/debug/trigger-select")
    async def debug_trigger_select():
        """手动模拟 spider 发送 select_tasks 事件，方便测试 modal 是否能弹出来
        修复 BUG-159: 不能用 controller.bridge.emit（跨线程调度可能死锁），
        改用 loop.call_soon 调度到事件循环的下一次迭代执行
        """
        import logging
        items = [
            {"title": "测试视频 1: 演示 modal 弹窗是否正常显示", "index": 0},
            {"title": "测试视频 2: 检查 z-index 和 position:fixed", "index": 1},
            {"title": "测试视频 3: 验证全选/反选/取消/开始下载按钮", "index": 2},
            {"title": "测试视频 4: 与 GUI SelectionDialog 视觉对照", "index": 3},
        ]
        loop = asyncio.get_running_loop()
        # 直接用 loop.call_soon 把 broadcast 协程排入下次事件循环迭代
        # 不在当前请求中等待，避免阻塞 HTTP 响应
        loop.call_soon(lambda: loop.create_task(manager.broadcast("select_tasks", {"items": items})))
        logging.info("[DEBUG] 已调度 select_tasks 测试事件")
        return {"status": "ok", "items_sent": len(items)}

    @app.delete("/api/video/{video_id}")
    async def delete_video(video_id: str):
        # 与 WebSocket delete_video 对齐：使用 async_delete_video，文件 I/O 在线程池中执行
        await controller.async_delete_video(video_id)
        return {"status": "ok"}

    @app.post("/api/video/rename")
    async def rename_video(body: dict):
        # 与 GUI 内联编辑器对齐：参数必须是字符串
        video_id = body.get("video_id", "")
        new_title = body.get("new_title", "")
        if not isinstance(video_id, str) or not isinstance(new_title, str):
            return {"status": "error", "error": "video_id 和 new_title 必须是字符串"}
        # 与 WebSocket rename_video 对齐：使用 async_rename_video，文件 I/O 在线程池中执行
        result = await controller.async_rename_video(video_id, new_title)
        return result

    @app.post("/api/download")
    async def download_video(request: Request, body: dict):
        """直接下载指定 URL 的视频（与 CLI download 命令和 SDK download_video 对齐）。"""
        context = composition.get_request_context(request)
        return await context.workflow.direct_download(body, log_error=False)

    # ---- 媒体文件服务（支持 Range 请求，视频拖拽进度条必需） ----

    @app.get("/api/media/{video_id}")
    async def get_media(video_id: str, range: str | None = None):
        path = controller.get_media_path(video_id)
        # 修复 BUG-150: 文件不存在返回 404，让 video 元素正确触发 onerror
        if not path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="file not found")
        try:
            path, file_size, content_type = await asyncio.get_running_loop().run_in_executor(None, _media_file_info, path)
        except FileNotFoundError:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="file not found")

        # 处理 Range 请求（视频 seek 必需）
        range_header = range
        if range_header:
            range_match = __import__("re").match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                chunk_size = end - start + 1

                return StreamingResponse(
                    _iter_file_range(path, start, chunk_size),
                    status_code=206,
                    media_type=content_type,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(chunk_size),
                    },
                )

        # 无 Range 请求，返回完整文件
        return FileResponse(
            path,
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    # ---- 目录浏览 API（服务端文件系统，替代浏览器端文件夹选择器） ----

    @app.get("/api/dir/list")
    async def list_directory(path: str = ""):
        """列出指定目录下的子目录，供前端文件夹选择器使用。"""
        if not path:
            path = controller.current_save_dir

        try:
            return await asyncio.get_running_loop().run_in_executor(None, _list_directory_payload, path)
        except PermissionError:
            return {"error": "无权限访问该目录", "path": path}
        except OSError as exc:
            return {"error": str(exc), "path": path}

    @app.post("/api/dir/change")
    async def change_dir(request: Request):
        """更改目录并返回扫描结果。

        修复 BUG-182/184/185/186: 完全不调用 manager.broadcast，只返回 HTTP 响应。
        前端根据 HTTP 响应直接更新 UI，不依赖 WebSocket 推送。
        cfg.set 在 run_in_executor 中执行，避免阻塞事件循环。
        修复 BUG-186: 整个端点包在一个 try/except 里，修复 try 间隙问题。
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            try:
                body = await request.json()
            except Exception:
                body = {}

            if not isinstance(body, dict):
                return {"status": "error", "error": "请求体必须是 JSON 对象"}

            directory = body.get("directory", "")
            if not directory:
                return {"status": "error", "error": "目录路径不能为空"}
            # 与 GUI QFileDialog 对齐：directory 必须是字符串
            if not isinstance(directory, str):
                return {"status": "error", "error": "directory 必须是字符串"}

            logger.info(f"[change_dir] 开始: {directory}")

            # 1. 更新控制器状态
            controller.current_save_dir = directory

            # 2. cfg.set 在线程池中执行（避免文件 I/O 阻塞事件循环）
            def _save_cfg():
                try:
                    cfg.set("common", "save_directory", directory)
                except Exception as e:
                    logger.warning(f"[change_dir] cfg.set 失败: {e}")
            await asyncio.get_running_loop().run_in_executor(None, _save_cfg)

            # 3. 清空旧数据
            _clear_controller_videos(controller)

            # 4. 扫描新目录（文件 I/O 在线程池中执行）
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
            try:
                scan_limit = int(scan_limit)
            except (ValueError, TypeError):
                scan_limit = 1000

            result = await asyncio.get_running_loop().run_in_executor(
                None,
                controller.file_service.scan_directory,
                directory,
                scan_limit,
            )
            logger.info(f"[change_dir] 扫描完成: {result.total_count} 个文件")

            # 5. 构建返回数据
            items = []
            for item in result.items:
                # 与 SDK scan_directory 一致：本地文件标记为"✅ 本地"，进度 100%
                item.status = "✅ 本地"
                item.progress = 100
                _store_controller_video(controller, item)
                try:
                    items.append(controller._video_item_to_dict(item))
                except Exception:
                    items.append({
                        "id": item.id, "title": getattr(item, 'title', ''),
                        "url": "", "source": "", "status": "✅ 本地", "progress": 100,
                        "local_path": getattr(item, 'local_path', ''),
                        "content_type": "", "meta": {},
                    })

            msg = f"已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
            if result.truncated:
                msg = f"文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
            elif result.total_count == 0:
                msg = "该目录下没有找到视频或图片"

            return {
                "status": "ok",
                "directory": directory,
                "items": items,
                "total_count": result.total_count,
                "video_count": result.video_count,
                "image_count": result.image_count,
                "truncated": result.truncated,
                "original_count": result.original_count,
                "message": msg,
            }
        except Exception as exc:
            logger.error(f"[change_dir] 失败: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc)}

    # 修复 BUG-157: 弹原生系统文件夹选择对话框
    # 关键: 不能在 asyncio 事件循环中同步调用 QFileDialog（会冻结事件循环）
    # 必须用 run_in_executor + 子进程隔离
    def _powershell_pick_dir():
        """在子进程中用 PowerShell 调 .NET FolderBrowserDialog 弹原生窗口
        不依赖 Qt/PyQt6，可在任意环境下工作
        """
        import subprocess
        script = (
            'Add-Type -AssemblyName System.Windows.Forms | Out-Null; '
            '$f = New-Object System.Windows.Forms.FolderBrowserDialog; '
            '$f.Description = "选择保存目录"; '
            '$f.ShowNewFolderButton = $true; '
            'if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) '
            '{ Write-Output $f.SelectedPath }'
        )
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                capture_output=True, text=True, timeout=300
            )
            path = result.stdout.strip()
            return path if path else None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    @app.post("/api/dir/pick-native")
    async def pick_native_folder():
        """弹出系统原生文件夹选择对话框（不阻塞 asyncio 事件循环）"""
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(None, _powershell_pick_dir)
            return {"path": path or ""}
        except Exception as exc:
            return {"error": str(exc)}

    # ---- 调试文件下载 API ----

    def _latest_log_file_response():
        from app.services.debug_service import DebugArtifactsService

        svc = DebugArtifactsService()
        log_path = svc.latest_log_path()
        if log_path and os.path.exists(log_path):
            return FileResponse(log_path, filename=os.path.basename(log_path), media_type="text/plain")
        return {"error": "日志文件不存在"}

    def _latest_error_summary_file_response():
        from app.services.debug_service import DebugArtifactsService

        svc = DebugArtifactsService()
        summary_path = svc.latest_error_summary_path()
        if summary_path and os.path.exists(summary_path):
            return FileResponse(summary_path, filename=os.path.basename(summary_path), media_type="text/markdown")
        return {"error": "错误摘要不存在"}

    @app.get("/api/debug/latest-log")
    async def download_latest_log():
        """下载最新调试日志。"""
        return await asyncio.get_running_loop().run_in_executor(None, _latest_log_file_response)

    @app.get("/api/debug/error-summary")
    async def download_error_summary():
        """下载最新错误摘要。"""
        return await asyncio.get_running_loop().run_in_executor(None, _latest_error_summary_file_response)

    # ---- WebSocket ----

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        binding = await composition.ws_session_binder.bind(ws)
        if binding is None:
            return
        await manager.connect(ws, binding.session_id)
        await composition.ws_bootstrapper.initialize(
            ws,
            binding.context,
            create_task_fn=asyncio.create_task,
        )
        await composition.ws_runtime.run(ws, binding.context)

    # ---- 静态文件 ----

    @app.get("/")
    async def serve_index():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return _apply_no_cache_headers(FileResponse(str(index_path)))
        return {"error": "index.html not found"}

    # 挂载静态目录（放在最后，避免覆盖 API 路由）
    if STATIC_DIR.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
    if UI_ICON_DIR.exists():
        app.mount("/ui-icon", StaticFiles(directory=str(UI_ICON_DIR)), name="ui-icon")

    return app
