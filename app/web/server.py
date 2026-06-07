"""FastAPI 服务器：REST API + WebSocket + 静态文件服务。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import cfg
from app.debug_logger import debug_logger

# WebController 在 create_app() 中延迟初始化
controller = None

STATIC_DIR = Path(__file__).parent / "static"

# 确保 MIME 类型已注册
mimetypes.init()


def create_app(lifespan=None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="Universal Crawler Pro", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # 修复 BUG-186: wildcard origin 不能带 credentials
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- WebSocket 连接管理 ----

    class ConnectionManager:
        def __init__(self):
            self.active_connections: list[WebSocket] = []

        async def connect(self, ws: WebSocket):
            await ws.accept()
            self.active_connections.append(ws)

        def disconnect(self, ws: WebSocket):
            if ws in self.active_connections:
                self.active_connections.remove(ws)

        async def broadcast(self, event_type: str, data=None):
            msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
            for ws in list(self.active_connections):
                try:
                    await ws.send_text(msg)
                except Exception:
                    self.active_connections.remove(ws)

    manager = ConnectionManager()

    # ---- 初始化 WebController ----

    global controller
    from app.web.controller import WebController
    # 不在 create_app 时获取事件循环，因为 uvicorn 可能使用不同的事件循环
    # 传入 None，在首次 emit 时延迟获取正确的事件循环
    controller = WebController(None, manager.broadcast)

    # ---- REST API ----

    def _build_selection_strategy(selection_dict: dict | None):
        """从 REST API 的 selection 参数构建 SelectionStrategy 实例。"""
        from cli.selection import RuleSelection, PipeSelection

        if not selection_dict:
            return RuleSelection(all_items=True)  # 默认全选

        strategy = selection_dict.get("strategy", "all")

        if strategy == "all":
            return RuleSelection(all_items=True)
        elif strategy == "first":
            return RuleSelection(first=True)
        elif strategy == "last":
            return RuleSelection(last=True)
        elif strategy == "rule":
            select_val = selection_dict.get("select")
            exclude_val = selection_dict.get("exclude")
            # 与 SDK 对齐：select/exclude 必须是字符串或 null
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
        elif strategy == "preload":
            choices = selection_dict.get("choices", [])
            # 与 SDK 对齐：choices 必须是二维数组
            if not isinstance(choices, list):
                return None
            # 校验每个元素也是列表（二维数组）
            for round_choices in choices:
                if not isinstance(round_choices, list):
                    return None
            return PipeSelection(preloaded_choices=choices)
        elif strategy == "interactive":
            # 与 SDK _resolve_selection 对齐：支持 "interactive" 策略
            from cli.selection import InteractiveTTYSelection
            return InteractiveTTYSelection()
        elif strategy == "pipe":
            # 与 SDK _resolve_selection 对齐：支持 "pipe" 策略
            return PipeSelection()
        else:
            # 与 CLI argparse choices 对齐：未知策略返回错误而非静默默认
            return None

    def _merge_default_config(source: str, user_config: dict) -> dict:
        """合并平台默认配置 + 用户配置（与 GUI read_*_run_options 对齐）。

        GUI 中 read_douyin_run_options 返回 {"max_items": 20, "timeout": 10}，
        read_bilibili_run_options 返回 {"max_pages": 1}，
        read_kuaishou_run_options 返回 {"max_items": 20}，
        read_missav_run_options 返回 {"individual_only": False, "priority": "中文字幕优先", "proxy": "..."}。

        优先从 cfg 持久化配置读取默认值（与 GUI 对齐），
        用户 config 覆盖 cfg 默认值。
        """
        from cli.defaults import get_platform_defaults, build_missav_proxy_url

        merged = get_platform_defaults(source)
        # 与 CLI _build_config 对齐：过滤 None 值，避免覆盖默认值
        # （CLI argparse 只在用户显式提供参数时才设置，不会用 None 覆盖默认）
        filtered = {k: v for k, v in user_config.items() if v is not None}
        merged.update(filtered)
        # MissAV 代理转换（与 GUI build_missav_proxy_url 一致）
        if source == "missav" and "proxy" in merged and merged["proxy"] is not None:
            merged["proxy"] = build_missav_proxy_url(merged["proxy"])
        return merged

    def _validate_config_types(user_config: dict) -> str | None:
        """校验已知 config 参数类型，与 CLI argparse type 和 SDK _validate_config 对齐。

        委托给 cli.defaults.validate_config_types 统一实现，
        确保 CLI/SDK/REST API 三层校验逻辑完全一致。
        """
        from cli.defaults import validate_config_types as _shared_validate
        return _shared_validate(user_config)

    @app.get("/api/ping")
    async def ping():
        from cli import __version__
        return {"status": "ok", "version": __version__}

    @app.get("/api/platforms")
    async def get_platforms():
        return controller.get_platforms()

    @app.get("/api/config")
    async def get_config():
        return controller.get_config()

    @app.put("/api/config")
    async def update_config(updates: dict):
        # 与 GUI 设置对话框对齐：updates 必须是 dict
        if not isinstance(updates, dict):
            return {"status": "error", "error": "请求体必须是 JSON 对象"}
        controller.update_config(updates)
        return {"status": "ok"}

    @app.get("/api/state")
    async def get_state():
        return controller.get_state()

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
            controller.videos.clear()

            result = await asyncio.get_running_loop().run_in_executor(
                None, controller.file_service.scan_directory, directory, scan_limit,
            )

            items = []
            for item in result.items:
                # 与 SDK scan_directory 一致：本地文件标记为"✅ 本地"，进度 100%
                item.status = "✅ 本地"
                item.progress = 100
                controller.videos[item.id] = item
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

        def _run_search():
            from cli.runner import CLIRunner
            runner = CLIRunner(
                source=source,
                keyword=keyword,
                save_dir=save_dir,
                selection_strategy=strategy,
                config=merged_config,
                verbose=False,
                log_to_stderr=False,
                timeout=timeout,
                download=download,
            )
            return runner.run()

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _run_search)
            return result
        except Exception as exc:
            logger.error(f"[search] 搜索失败: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc)}

    @app.post("/api/crawl/start")
    async def start_crawl(body: dict):
        source = body.get("source", "")
        keyword = body.get("keyword", "")
        # 与 GUI 对齐：此端点始终触发下载（与 GUI on_start_crawl 一致），不支持 download 参数
        # 如需只搜索不下载，请使用 /api/search 并传 download: false
        if "download" in body:
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "此端点始终触发下载，不支持 download 参数。如需只搜索不下载，请使用 POST /api/search 并传 download: false"}
        # 与 GUI QLineEdit 对齐：source 和 keyword 必须是字符串
        if not isinstance(source, str) or not isinstance(keyword, str):
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "source 和 keyword 必须是字符串"}
        # 与 GUI inp_search.text().strip() 对齐：去除前后空白
        keyword = keyword.strip()
        if not source or not keyword:
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "source 和 keyword 为必填参数"}

        # 与 GUI QComboBox 和 CLI choices 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        if not registry.get_plugin(source):
            valid_ids = [p.id for p in registry.get_all_plugins()]
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": f"无效平台: {source}。支持: {valid_ids}"}

        # 与 GUI ApplicationController._has_active_spider 对齐：先检查是否有爬虫在运行
        if controller.current_spider and controller.current_spider.isRunning():
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "当前已有任务在运行，请先停止或等待结束"}

        user_config = body.get("config", {})
        # 与 GUI 对齐：Qt 控件保证 config 是 dict，REST API 需显式校验
        if not isinstance(user_config, dict):
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "config 必须是 JSON 对象"}
        # 与 CLI argparse type 和 SDK _validate_config 对齐：校验已知 config 参数类型
        config_err = _validate_config_types(user_config)
        if config_err:
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": config_err}
        selection_dict = body.get("selection")
        # 与 GUI 对齐：selection 必须是 dict 或 null
        if selection_dict is not None and not isinstance(selection_dict, dict):
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "selection 必须是 JSON 对象或 null"}
        # 与 CLI argparse choices 对齐：未知策略返回错误而非静默默认
        # 与 /api/search 对齐：selection: {} 等价于 selection: null，都走默认全选
        if selection_dict is not None:
            strategy = _build_selection_strategy(selection_dict)
            if strategy is None:
                valid_strategies = ["all", "first", "last", "rule", "preload", "interactive", "pipe"]
                await manager.broadcast("crawl_state", {"is_running": False})
                return {"status": "error", "error": f"无效选择策略。支持: {valid_strategies}"}
            controller._pending_selection_strategy = strategy
        else:
            controller._pending_selection_strategy = None

        # 合并平台默认配置（get_platform_defaults，与 GUI read_*_run_options 一致）
        merged_config = _merge_default_config(source, user_config)

        # 与 /api/search 对齐：支持 save_dir 参数
        # 仅在确认爬虫成功启动后才保留 save_dir，失败时回滚，避免副作用泄漏
        old_save_dir = controller.current_save_dir
        save_dir = body.get("save_dir")
        # 与 GUI QFileDialog 对齐：save_dir 必须是字符串或 null
        if save_dir is not None and not isinstance(save_dir, str):
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": "save_dir 必须是字符串或 null"}
        if save_dir:
            controller.current_save_dir = save_dir

        try:
            controller.start_crawl(source, keyword, merged_config)
        except Exception as exc:
            # 异常时回滚 save_dir 和清理 _pending_selection_strategy，避免副作用泄漏
            controller.current_save_dir = old_save_dir
            controller._pending_selection_strategy = None
            await manager.broadcast("crawl_state", {"is_running": False})
            return {"status": "error", "error": f"启动爬虫异常: {exc}"}
        # start_crawl() 内部已处理所有错误情况（异步调度到 Qt 主线程后，
        # 成功/失败都会通过 bridge.emit 推送 crawl_state 事件）
        return {"status": "ok"}

    @app.post("/api/crawl/stop")
    async def stop_crawl():
        controller.stop_crawl()
        return {"status": "ok"}

    @app.post("/api/crawl/select")
    async def select_tasks(body: dict):
        # 与 GUI SelectionDialog 对齐：取消时 indices 可以是 None，确认时必须是整数列表。
        # 同时与 GUI 对齐：必须有正在运行的爬虫才能进行二次选择
        if not controller.current_spider or not controller.current_spider.isRunning():
            return {"status": "error", "error": "当前没有正在运行的爬虫，无法进行二次选择"}
        indices = body.get("indices", [])
        if indices is None:
            controller.resume_spider_selection(None)
            return {"status": "ok"}
        if not isinstance(indices, list):
            return {"status": "error", "error": "indices 必须是整数数组"}
        try:
            indices = [int(i) for i in indices]
        except (ValueError, TypeError):
            return {"status": "error", "error": "indices 必须是整数数组"}
        controller.resume_spider_selection(indices)
        return {"status": "ok"}

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
    async def download_video(body: dict):
        """直接下载指定 URL 的视频（与 CLI download 命令和 SDK download_video 对齐）。"""
        import time as _time
        _dl_start = _time.time()
        url = body.get("url", "")
        source = body.get("source", "")
        # 与 CLI/SDK 对齐：title 默认使用 URL（而非空字符串）
        # 修复：先校验 title 类型再应用默认值，避免非字符串 falsy 值（如 0）被静默替换为 URL
        title = body.get("title")
        if title is not None and not isinstance(title, str):
            return {"status": "error", "error": "title 必须是字符串"}
        title = title or url
        save_dir = body.get("save_dir")
        # 与 CLI --run-timeout 和 SDK timeout 对齐：支持自定义超时
        timeout = body.get("timeout", 300)
        # 与 SDK download_video(config=) 对齐：支持平台特定配置（如 missav proxy）
        user_config = body.get("config", {})

        # 与 CLI download 命令对齐：参数校验
        if not isinstance(url, str) or not isinstance(source, str):
            return {"status": "error", "error": "url 和 source 必须是字符串"}
        if not url or not source:
            return {"status": "error", "error": "url 和 source 为必填参数"}
        if save_dir is not None and not isinstance(save_dir, str):
            return {"status": "error", "error": "save_dir 必须是字符串或 null"}
        # 与 GUI 对齐：Qt 控件保证 config 是 dict，REST API 需显式校验
        if not isinstance(user_config, dict):
            return {"status": "error", "error": "config 必须是 JSON 对象"}
        # 与 CLI argparse type 和 SDK _validate_config 对齐：校验已知 config 参数类型
        config_err = _validate_config_types(user_config)
        if config_err:
            return {"status": "error", "error": config_err}
        # 与 REST API /api/search 对齐：timeout 必须是数字
        try:
            timeout = float(timeout)
        except (ValueError, TypeError):
            return {"status": "error", "error": "timeout 必须是数字"}
        # 与 SDK 对齐：timeout 必须大于 0
        if timeout <= 0:
            return {"status": "error", "error": "timeout 必须大于 0"}
        # 与 CLI argparse choices 对齐：校验 source 是否为有效平台 ID
        from app.core.plugin_registry import registry
        plugin = registry.get_plugin(source)
        if not plugin:
            valid_ids = [p.id for p in registry.get_all_plugins()]
            return {"status": "error", "error": f"无效平台: {source}。支持: {valid_ids}"}

        # 与 /api/search 对齐：save_dir 未提供时使用 controller.current_save_dir
        effective_save_dir = save_dir or controller.current_save_dir
        # 与 CLI download 命令对齐：直接传原始 user_config 给 SDK，由 SDK 内部合并平台默认配置
        # （CLI 也是传原始 config 给 sdk.download_video()，不在外部预合并，避免冗余双重合并）
        from cli.sdk import UcrawlSDK
        sdk = UcrawlSDK(save_dir=effective_save_dir)

        # 与 WebController _on_task_started 对齐：广播 task_started 让 WebUI 实时更新
        # （REST API/WebSocket download 使用 sdk.download_video() 而非 controller.dl_manager，
        #   所以需要手动广播 task_started/task_finished 事件，与爬虫下载流程对齐）
        # 与 GUI _on_spider_item_found 对齐：先创建 pending_item 为 "⏳ 等待中" 状态，
        # 广播 item_found，再切换到 "⏳ 下载中..." 并广播 task_started + video_state_changed。
        # GUI 流程：item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished
        from app.models.video_item import VideoItem
        pending_item = VideoItem(
            url=url, title=title or url, source=source,
            status="⏳ 等待中", progress=0,
        )
        # 与 GUI spider build_download_meta 对齐：设置 trace_id 和 content_type
        # GUI spider 在 emit_video 时通过 build_download_meta 设置 trace_id，
        # DownloadWorker._trace_id() 依赖此字段做日志关联。
        # SDK download_video 也会设置 trace_id，但 pending_item 在 SDK 调用之前创建，
        # 需要提前设置，确保 task_started 事件中就能包含正确的 trace_id 和 content_type。
        import uuid as _uuid
        _source_prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
        pending_item.meta["trace_id"] = f"{_source_prefix}-dl-{_uuid.uuid4().hex[:8]}"
        # 与 GUI spider 结果对齐：从 URL 推断 content_type（SDK 也会推断，但提前设置让 task_started 事件包含）
        from cli.defaults import infer_content_type_from_url
        _pre_ct = infer_content_type_from_url(url)
        if _pre_ct:
            pending_item.meta["content_type"] = _pre_ct
        controller.videos[pending_item.id] = pending_item
        await manager.broadcast("item_found", controller._video_item_to_dict(pending_item))
        # 与 GUI _on_task_started 对齐：切换到 "⏳ 下载中..." 并广播 task_started + video_state_changed
        # 与 WebController _on_task_started 对齐：task_started 包含 title/content_type
        pending_item.status = "⏳ 下载中..."
        await manager.broadcast("task_started", {
            "video_id": pending_item.id, "local_path": "",
            "title": pending_item.title,
            "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
        })
        await manager.broadcast("video_state_changed", {"video_id": pending_item.id, "status": "⏳ 下载中...", "progress": 0})

        try:
            # 与 GUI DownloadManager task_progress 信号对齐：通过 progress_callback 实时广播进度
            # （GUI 通过 dl_manager.task_progress 信号实时更新进度条，REST API/WebSocket download
            #   使用 sdk.download_video() 而非 controller.dl_manager，因此需要通过回调桥接进度事件）
            def _on_download_progress(pct: int):
                pending_item.progress = pct
                # 与 WebController _on_task_progress 对齐：广播 task_progress 和 video_state_changed
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
                # task_progress 与 WebController _on_task_progress 广播格式对齐
                loop.create_task(manager.broadcast("task_progress", {"video_id": pending_item.id, "progress": pct}))
                # video_state_changed 与 WebController _apply_video_state 广播格式对齐
                loop.create_task(manager.broadcast("video_state_changed", {"video_id": pending_item.id, "status": pending_item.status, "progress": pct}))

            result = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: sdk.download_video(url=url, source=source, title=title, save_dir=effective_save_dir, timeout=timeout, config=user_config, progress_callback=_on_download_progress),
            )
        except (TypeError, ValueError) as exc:
            # 与 SDK 返回 error 结果路径对齐：保留 pending_item，设置 "❌ 失败" 状态和 download_error
            # （不删除 pending_item，与 GUI _on_download_error 行为一致：失败条目保留在列表中可见）
            pending_item.status = "❌ 失败"
            pending_item.progress = 0
            if pending_item.meta is None:
                pending_item.meta = {}
            pending_item.meta["download_error"] = str(exc)
            # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
            await manager.broadcast("task_error", {
                "video_id": pending_item.id, "error": str(exc),
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "title": pending_item.title,
            })
            # 与 WebController _apply_video_state 对齐：失败时 video_state_changed 包含 local_path 和 content_type
            await manager.broadcast("video_state_changed", {
                "video_id": pending_item.id, "status": "❌ 失败", "progress": 0,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
            })
            await manager.broadcast("log", {"message": f"❌ 下载参数错误: {exc}"})
            # 与 SDK download_video 错误结果对齐：返回完整字段
            # 与 video_state_changed 对齐：local_path 使用 pending_item.local_path or ""
            return {
                "status": "error", "error": str(exc), "video_id": pending_item.id,
                "url": url, "source": source, "title": title or url,
                "save_dir": effective_save_dir, "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "meta": {"download_error": str(exc)},
                "elapsed": round(_time.time() - _dl_start, 2),
            }
        except Exception as exc:
            # 与 SDK 返回 error 结果路径对齐：保留 pending_item，设置 "❌ 失败" 状态和 download_error
            # （不删除 pending_item，与 GUI _on_download_error 行为一致：失败条目保留在列表中可见）
            pending_item.status = "❌ 失败"
            pending_item.progress = 0
            if pending_item.meta is None:
                pending_item.meta = {}
            pending_item.meta["download_error"] = f"下载失败: {exc}"
            # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
            await manager.broadcast("task_error", {
                "video_id": pending_item.id, "error": f"下载失败: {exc}",
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "title": pending_item.title,
            })
            # 与 WebController _apply_video_state 对齐：失败时 video_state_changed 包含 local_path 和 content_type
            await manager.broadcast("video_state_changed", {
                "video_id": pending_item.id, "status": "❌ 失败", "progress": 0,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
            })
            await manager.broadcast("log", {"message": f"❌ 下载失败: {exc}"})
            # 与 SDK download_video 错误结果对齐：返回完整字段
            # 与 video_state_changed 对齐：local_path 使用 pending_item.local_path or ""
            return {
                "status": "error", "error": f"下载失败: {exc}", "video_id": pending_item.id,
                "url": url, "source": source, "title": title or url,
                "save_dir": effective_save_dir, "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "meta": {"download_error": f"下载失败: {exc}"},
                "elapsed": round(_time.time() - _dl_start, 2),
            }
        finally:
            # 防御性处理：确保 sdk 存在后再 close
            try:
                sdk.close()
            except Exception:
                pass

        # 就地更新 pending_item 属性，保持 video_id 一致（避免前端收到两个不同的 video_id）
        # 与 GUI _on_task_finished/_on_task_error 对齐：更新 item 状态
        if result.get("status") == "ok":
            pending_item.status = "✅ 完成"
            pending_item.progress = 100
            local_path = result.get("local_path", "")
            if local_path:
                pending_item.local_path = local_path
            pending_item.title = result.get("title", pending_item.title)
            if pending_item.meta is None:
                pending_item.meta = {}
            content_type = result.get("content_type", "")
            # 与 GUI spider 结果对齐：SDK 已通过 infer_content_type 推断 content_type，
            # 若仍为空则从 pending_item.local_path 二次推断（防御性兜底）
            if not content_type and local_path:
                from cli.defaults import infer_content_type
                content_type = infer_content_type(local_path)
                result["content_type"] = content_type
            if content_type:
                pending_item.meta["content_type"] = content_type
            pending_item.meta.update(result.get("meta", {}))
            # 同步 SDK 返回的 video_id 到 result，确保客户端可用
            result["video_id"] = pending_item.id
            # 与 WebController _on_task_finished 对齐：广播 task_finished 包含完整信息
            # （WebController 的 task_finished 只有 video_id 和 local_path，REST API 增补
            #   content_type 和 title，让 WebSocket 客户端无需额外请求即可获取完整下载结果）
            await manager.broadcast("task_finished", {
                "video_id": pending_item.id,
                "local_path": local_path,
                "content_type": content_type,
                "title": pending_item.title,
            })
            # 与 WebController _apply_video_state 对齐：video_state_changed 包含 local_path 和 content_type
            # （WebController 的 video_state_changed 只有 video_id/status/progress，REST API 增补
            #   local_path 和 content_type，让 WebSocket 客户端可更新本地缓存的 item 信息）
            await manager.broadcast("video_state_changed", {
                "video_id": pending_item.id,
                "status": "✅ 完成",
                "progress": 100,
                "local_path": local_path,
                "content_type": content_type,
            })
            await manager.broadcast("log", {"message": f"✅ 下载完成: {pending_item.title}"})
        else:
            error_msg = result.get("error", "下载失败")
            # 与 GUI/CLI 对齐：区分 "❌ 超时" 和 "❌ 失败"
            if result.get("status") == "timeout" or "超时" in error_msg:
                pending_item.status = "❌ 超时"
            else:
                pending_item.status = "❌ 失败"
            pending_item.progress = 0
            if pending_item.meta is None:
                pending_item.meta = {}
            pending_item.meta["download_error"] = error_msg
            # 与成功路径对齐：从 SDK 结果更新 pending_item 属性
            if result.get("local_path"):
                pending_item.local_path = result["local_path"]
            if result.get("title"):
                pending_item.title = result["title"]
            if result.get("meta") and isinstance(result["meta"], dict):
                pending_item.meta.update(result["meta"])
            # 同步 SDK 返回的 video_id 到 result
            result["video_id"] = pending_item.id
            # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
            await manager.broadcast("task_error", {
                "video_id": pending_item.id, "error": error_msg,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                "title": pending_item.title,
            })
            # 与 WebController _apply_video_state 对齐：失败/超时时 video_state_changed 包含 local_path 和 content_type
            await manager.broadcast("video_state_changed", {
                "video_id": pending_item.id, "status": pending_item.status, "progress": 0,
                "local_path": pending_item.local_path or "",
                "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
            })
            await manager.broadcast("log", {"message": f"❌ 下载失败: {error_msg}"})

        return result

    # ---- 媒体文件服务（支持 Range 请求，视频拖拽进度条必需） ----

    @app.get("/api/media/{video_id}")
    async def get_media(video_id: str, range: str | None = None):
        path = controller.get_media_path(video_id)
        # 修复 BUG-150: 文件不存在返回 404，让 video 元素正确触发 onerror
        if not path or not os.path.exists(path):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="file not found")

        file_size = os.path.getsize(path)
        content_type, _ = mimetypes.guess_type(path)
        if not content_type:
            content_type = "application/octet-stream"

        # 处理 Range 请求（视频 seek 必需）
        range_header = range
        if range_header:
            range_match = __import__("re").match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                chunk_size = end - start + 1

                async def stream_range():
                    with open(path, "rb") as f:
                        f.seek(start)
                        remaining = chunk_size
                        while remaining > 0:
                            read_size = min(8192, remaining)
                            data = f.read(read_size)
                            if not data:
                                break
                            remaining -= len(data)
                            yield data

                return StreamingResponse(
                    stream_range(),
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

        if not os.path.exists(path):
            return {"error": "目录不存在", "path": path}

        try:
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
            # 获取常见根目录（Windows 驱动器）
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
            controller.videos.clear()

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
                controller.videos[item.id] = item
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

    @app.get("/api/debug/latest-log")
    async def download_latest_log():
        """下载最新调试日志。"""
        from app.services.debug_service import DebugArtifactsService
        svc = DebugArtifactsService()
        log_path = svc.latest_log_path()
        if log_path and os.path.exists(log_path):
            return FileResponse(log_path, filename=os.path.basename(log_path), media_type="text/plain")
        return {"error": "日志文件不存在"}

    @app.get("/api/debug/error-summary")
    async def download_error_summary():
        """下载最新错误摘要。"""
        from app.services.debug_service import DebugArtifactsService
        svc = DebugArtifactsService()
        summary_path = svc.latest_error_summary_path()
        if summary_path and os.path.exists(summary_path):
            return FileResponse(summary_path, filename=os.path.basename(summary_path), media_type="text/markdown")
        return {"error": "错误摘要不存在"}

    # ---- WebSocket ----

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await manager.connect(ws)
        # 连接后立即推送当前状态
        try:
            state = controller.get_state()
            await ws.send_text(json.dumps({"type": "init_state", "data": state}, ensure_ascii=False))
            platforms = controller.get_platforms()
            await ws.send_text(json.dumps({"type": "platforms", "data": platforms}, ensure_ascii=False))
            config_data = controller.get_config()
            await ws.send_text(json.dumps({"type": "config", "data": config_data}, ensure_ascii=False))
        except Exception:
            pass

        # 首次连接自动扫描目录（与桌面 GUI 启动行为一致）
        # 修复 BUG-180: 使用 async_scan_local_dir，文件 I/O 在线程池中执行，
        # bridge.emit 在事件循环中调用，避免跨线程调度静默失败
        try:
            controller.bridge._loop = asyncio.get_running_loop()
            await controller.async_scan_local_dir()
        except Exception:
            pass

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await _handle_client_message(msg)
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    async def _handle_client_message(msg: dict):
        """处理客户端 WebSocket 消息。

        修复 BUG-182: 每个消息类型都加 try/except，防止单个消息处理异常
        杀死整个 WebSocket 连接。异常通过 WebSocket 推送给前端显示。
        """
        import logging
        msg_type = msg.get("type", "")
        data = msg.get("data", {}) or {}

        try:
            if msg_type == "start_crawl":
                source = data.get("source", "")
                keyword = data.get("keyword", "")
                # 与 REST API /api/crawl/start 对齐：此端点始终触发下载，不支持 download 参数
                if "download" in data:
                    await manager.broadcast("log", {"message": "❌ 此端点始终触发下载，不支持 download 参数。如需只搜索不下载，请使用 POST /api/search 并传 download: false"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 GUI QLineEdit 对齐：source 和 keyword 必须是字符串
                if not isinstance(source, str) or not isinstance(keyword, str):
                    await manager.broadcast("log", {"message": "❌ source 和 keyword 必须是字符串"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 GUI inp_search.text().strip() 对齐：去除前后空白
                keyword = keyword.strip()
                if not source or not keyword:
                    await manager.broadcast("log", {"message": "❌ source 和 keyword 为必填参数"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 GUI QComboBox 和 CLI choices 对齐：校验 source 是否为有效平台 ID
                from app.core.plugin_registry import registry
                if not registry.get_plugin(source):
                    valid_ids = [p.id for p in registry.get_all_plugins()]
                    await manager.broadcast("log", {"message": f"❌ 无效平台: {source}。支持: {valid_ids}"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 GUI ApplicationController._has_active_spider 对齐：先检查是否有爬虫在运行
                if controller.current_spider and controller.current_spider.isRunning():
                    await manager.broadcast("log", {"message": "⚠️ 当前已有任务在运行，请先停止或等待结束"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                user_config = data.get("config", {})
                # 与 GUI 对齐：Qt 控件保证 config 是 dict，WebSocket 需显式校验
                if not isinstance(user_config, dict):
                    await manager.broadcast("log", {"message": "❌ config 必须是 JSON 对象"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 CLI argparse type 和 SDK _validate_config 对齐：校验已知 config 参数类型
                config_err = _validate_config_types(user_config)
                if config_err:
                    await manager.broadcast("log", {"message": f"❌ {config_err}"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 合并平台默认配置（get_platform_defaults，与 GUI read_*_run_options 一致）
                merged_config = _merge_default_config(source, user_config)
                # 与 REST API /api/crawl/start 对齐：支持 selection 自动选择策略
                selection_dict = data.get("selection")
                # 与 GUI 对齐：selection 必须是 dict 或 null
                if selection_dict is not None and not isinstance(selection_dict, dict):
                    await manager.broadcast("log", {"message": "❌ selection 必须是 JSON 对象或 null"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # 与 CLI argparse choices 对齐：未知策略返回错误而非静默默认
                # 与 /api/search 对齐：selection: {} 等价于 selection: null，都走默认全选
                if selection_dict is not None:
                    strategy = _build_selection_strategy(selection_dict)
                    if strategy is None:
                        valid_strategies = ["all", "first", "last", "rule", "preload", "interactive", "pipe"]
                        await manager.broadcast("log", {"message": f"❌ 无效选择策略。支持: {valid_strategies}"})
                        await manager.broadcast("crawl_state", {"is_running": False})
                        return
                    controller._pending_selection_strategy = strategy
                else:
                    controller._pending_selection_strategy = None
                # 与 REST API /api/crawl/start 对齐：支持 save_dir
                # 仅在确认爬虫成功启动后才保留 save_dir，失败时回滚，避免副作用泄漏
                old_save_dir = controller.current_save_dir
                save_dir = data.get("save_dir")
                # 与 GUI QFileDialog 对齐：save_dir 必须是字符串或 null
                if save_dir is not None and not isinstance(save_dir, str):
                    await manager.broadcast("log", {"message": "❌ save_dir 必须是字符串或 null"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                if save_dir:
                    controller.current_save_dir = save_dir
                try:
                    controller.start_crawl(
                        source,
                        keyword,
                        merged_config,
                    )
                except Exception as exc:
                    # 异常时回滚 save_dir 和清理 _pending_selection_strategy，避免副作用泄漏
                    controller.current_save_dir = old_save_dir
                    controller._pending_selection_strategy = None
                    await manager.broadcast("log", {"message": f"❌ 启动爬虫异常: {exc}"})
                    await manager.broadcast("crawl_state", {"is_running": False})
                    return
                # start_crawl() 内部已处理所有错误情况（异步调度到 Qt 主线程后，
                # 成功/失败都会通过 bridge.emit 推送 crawl_state 事件）
                # 不再在此处检查 current_spider，因为 spider 创建是异步的
            elif msg_type == "stop_crawl":
                controller.stop_crawl()
            elif msg_type == "select_tasks":
                # 与 REST API /api/crawl/select 对齐：取消时允许 None，确认时必须是整数列表。
                # 与 GUI SelectionDialog 对齐：QDialog.reject() 会返回 None。
                # 同时与 GUI 对齐：必须有正在运行的爬虫才能进行二次选择
                if not controller.current_spider or not controller.current_spider.isRunning():
                    await manager.broadcast("log", {"message": "❌ 当前没有正在运行的爬虫，无法进行二次选择"})
                    return
                indices = data.get("indices", [])
                if indices is None:
                    controller.resume_spider_selection(None)
                    return
                if not isinstance(indices, list):
                    await manager.broadcast("log", {"message": "❌ indices 必须是整数数组"})
                    return
                try:
                    indices = [int(i) for i in indices]
                except (ValueError, TypeError):
                    await manager.broadcast("log", {"message": "❌ indices 必须是整数数组"})
                    return
                controller.resume_spider_selection(indices)
            elif msg_type == "scan_dir":
                # 与 REST API /api/scan 对齐：支持 scan_limit 参数
                directory = data.get("directory")
                # 与 GUI QFileDialog 对齐：directory 必须是字符串
                if directory is not None and not isinstance(directory, str):
                    await manager.broadcast("log", {"message": "❌ directory 必须是字符串"})
                    return
                scan_limit = data.get("scan_limit")
                if scan_limit is not None:
                    # 与 SDK scan_directory 对齐：scan_limit 必须是整数
                    if not isinstance(scan_limit, int):
                        await manager.broadcast("log", {"message": "❌ scan_limit 必须是整数"})
                        return
                    # 与 SDK scan_directory 和 REST API /api/scan 对齐：scan_limit 必须大于 0
                    if scan_limit <= 0:
                        await manager.broadcast("log", {"message": "❌ scan_limit 必须大于 0"})
                        return
                await controller.async_scan_local_dir(data.get("directory"), scan_limit=scan_limit)
            elif msg_type == "change_dir":
                directory = data.get("directory", "")
                # 与 REST API /api/dir/change 对齐：校验目录非空
                if not directory:
                    await manager.broadcast("log", {"message": "❌ 目录路径不能为空"})
                    return
                # 与 GUI QFileDialog 对齐：directory 必须是字符串
                if not isinstance(directory, str):
                    await manager.broadcast("log", {"message": "❌ directory 必须是字符串"})
                    return
                await controller.async_change_dir(directory)
            elif msg_type == "change_theme":
                is_dark = data.get("dark_theme", True)
                # 与 GUI QCheckBox 对齐：dark_theme 必须是布尔值
                if not isinstance(is_dark, bool):
                    await manager.broadcast("log", {"message": "❌ dark_theme 必须是布尔值"})
                    return
                cfg.set("common", "dark_theme", is_dark)
                cfg.set("common", "theme", "dark" if is_dark else "light")
            elif msg_type == "change_source":
                new_source = data.get("source", "")
                # 与 GUI QComboBox 对齐：source 必须是字符串
                if not isinstance(new_source, str):
                    await manager.broadcast("log", {"message": "❌ source 必须是字符串"})
                    return
                # 与 GUI QComboBox 对齐：只允许有效平台 ID
                if new_source:
                    from app.core.plugin_registry import registry
                    if not registry.get_plugin(new_source):
                        valid_ids = [p.id for p in registry.get_all_plugins()]
                        await manager.broadcast("log", {"message": f"❌ 无效平台: {new_source}。支持: {valid_ids}"})
                        return
                cfg.set("common", "last_source", new_source)
            elif msg_type == "save_config":
                section = data.get("section", "")
                key = data.get("key", "")
                value = data.get("value")
                # 与 GUI 对齐：section 和 key 必须是字符串
                if not isinstance(section, str) or not isinstance(key, str):
                    await manager.broadcast("log", {"message": "❌ section 和 key 必须是字符串"})
                    return
                if section and key:
                    try:
                        cfg.set(section, key, value)
                    except Exception as exc:
                        await manager.broadcast("log", {"message": f"❌ 保存配置失败: {exc}"})
            elif msg_type == "delete_video":
                vid = data.get("video_id", "")
                # 与 REST API /api/video/{video_id} 对齐：video_id 必须是字符串
                if not isinstance(vid, str):
                    await manager.broadcast("log", {"message": "❌ video_id 必须是字符串"})
                    return
                await controller.async_delete_video(vid)
            elif msg_type == "rename_video":
                vid = data.get("video_id", "")
                title = data.get("new_title", "")
                # 与 REST API /api/video/rename 对齐：参数必须是字符串
                if not isinstance(vid, str) or not isinstance(title, str):
                    await manager.broadcast("log", {"message": "❌ video_id 和 new_title 必须是字符串"})
                    return
                await controller.async_rename_video(vid, title)
            elif msg_type == "download":
                # 与 REST API /api/download 对齐：直接下载指定 URL 的视频
                url = data.get("url", "")
                source = data.get("source", "")
                # 与 CLI/SDK 对齐：title 默认使用 URL（而非空字符串）
                # 修复：先校验 title 类型再应用默认值，避免非字符串 falsy 值（如 0）被静默替换为 URL
                dl_title = data.get("title")
                if dl_title is not None and not isinstance(dl_title, str):
                    await manager.broadcast("log", {"message": "❌ title 必须是字符串"})
                    return
                dl_title = dl_title or url
                # 与 CLI --run-timeout 和 SDK timeout 对齐：支持自定义超时
                dl_timeout = data.get("timeout", 300)
                # 与 SDK download_video(config=) 对齐：支持平台特定配置（如 missav proxy）
                user_config = data.get("config", {})
                # 与 CLI download 命令对齐：参数校验
                if not isinstance(url, str) or not isinstance(source, str):
                    await manager.broadcast("log", {"message": "❌ url 和 source 必须是字符串"})
                    return
                if not url or not source:
                    await manager.broadcast("log", {"message": "❌ url 和 source 为必填参数"})
                    return
                from app.core.plugin_registry import registry
                if not registry.get_plugin(source):
                    valid_ids = [p.id for p in registry.get_all_plugins()]
                    await manager.broadcast("log", {"message": f"❌ 无效平台: {source}。支持: {valid_ids}"})
                    return
                save_dir = data.get("save_dir")
                if save_dir is not None and not isinstance(save_dir, str):
                    await manager.broadcast("log", {"message": "❌ save_dir 必须是字符串或 null"})
                    return
                # 与 GUI 对齐：Qt 控件保证 config 是 dict，WebSocket 需显式校验
                if not isinstance(user_config, dict):
                    await manager.broadcast("log", {"message": "❌ config 必须是 JSON 对象"})
                    return
                # 与 CLI argparse type 和 SDK _validate_config 对齐：校验已知 config 参数类型
                config_err = _validate_config_types(user_config)
                if config_err:
                    await manager.broadcast("log", {"message": f"❌ {config_err}"})
                    return
                # 与 REST API /api/search 对齐：timeout 必须是数字
                try:
                    dl_timeout = float(dl_timeout)
                except (ValueError, TypeError):
                    await manager.broadcast("log", {"message": "❌ timeout 必须是数字"})
                    return
                # 与 SDK 对齐：timeout 必须大于 0
                if dl_timeout <= 0:
                    await manager.broadcast("log", {"message": "❌ timeout 必须大于 0"})
                    return
                # 与 /api/search 对齐：save_dir 未提供时使用 controller.current_save_dir
                effective_save_dir = save_dir or controller.current_save_dir
                # 与 CLI download 命令对齐：直接传原始 user_config 给 SDK，由 SDK 内部合并平台默认配置
                # （CLI 也是传原始 config 给 sdk.download_video()，不在外部预合并，避免冗余双重合并）
                from cli.sdk import UcrawlSDK
                sdk = UcrawlSDK(save_dir=effective_save_dir)

                # 与 WebController _on_task_started 对齐：广播 task_started 让 WebUI 实时更新
                # （REST API/WebSocket download 使用 sdk.download_video() 而非 controller.dl_manager，
                #   所以需要手动广播 task_started/task_finished 事件，与爬虫下载流程对齐）
                # 与 GUI _on_spider_item_found 对齐：先创建 pending_item 为 "⏳ 等待中" 状态，
                # 广播 item_found，再切换到 "⏳ 下载中..." 并广播 task_started + video_state_changed。
                # GUI 流程：item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished
                from app.models.video_item import VideoItem as _VideoItem
                pending_item = _VideoItem(
                    url=url, title=dl_title or url, source=source,
                    status="⏳ 等待中", progress=0,
                )
                # 与 GUI spider build_download_meta 对齐：设置 trace_id 和 content_type
                # （与 REST API /api/download 对齐，确保 task_started 事件包含完整信息）
                import uuid as _ws_uuid
                _ws_prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
                pending_item.meta["trace_id"] = f"{_ws_prefix}-dl-{_ws_uuid.uuid4().hex[:8]}"
                from cli.defaults import infer_content_type_from_url as _ws_infer_ct
                _ws_pre_ct = _ws_infer_ct(url)
                if _ws_pre_ct:
                    pending_item.meta["content_type"] = _ws_pre_ct
                controller.videos[pending_item.id] = pending_item
                await manager.broadcast("item_found", controller._video_item_to_dict(pending_item))
                # 与 GUI _on_task_started 对齐：切换到 "⏳ 下载中..." 并广播 task_started + video_state_changed
                # 与 WebController _on_task_started 对齐：task_started 包含 title/content_type
                pending_item.status = "⏳ 下载中..."
                await manager.broadcast("task_started", {
                    "video_id": pending_item.id, "local_path": "",
                    "title": pending_item.title,
                    "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                })
                await manager.broadcast("video_state_changed", {"video_id": pending_item.id, "status": "⏳ 下载中...", "progress": 0})

                try:
                    # 与 GUI DownloadManager task_progress 信号对齐：通过 progress_callback 实时广播进度
                    # （GUI 通过 dl_manager.task_progress 信号实时更新进度条，WebSocket download
                    #   使用 sdk.download_video() 而非 controller.dl_manager，因此需要通过回调桥接进度事件）
                    def _on_ws_download_progress(pct: int):
                        pending_item.progress = pct
                        # 与 WebController _on_task_progress 对齐：广播 task_progress 和 video_state_changed
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            return
                        loop.create_task(manager.broadcast("task_progress", {"video_id": pending_item.id, "progress": pct}))
                        loop.create_task(manager.broadcast("video_state_changed", {"video_id": pending_item.id, "status": pending_item.status, "progress": pct}))

                    result = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: sdk.download_video(url=url, source=source, title=dl_title, save_dir=effective_save_dir, timeout=dl_timeout, config=user_config, progress_callback=_on_ws_download_progress),
                    )
                except (TypeError, ValueError) as exc:
                    # 与 SDK 返回 error 结果路径对齐：保留 pending_item，设置 "❌ 失败" 状态和 download_error
                    # （不删除 pending_item，与 GUI _on_download_error 行为一致：失败条目保留在列表中可见）
                    pending_item.status = "❌ 失败"
                    pending_item.progress = 0
                    if pending_item.meta is None:
                        pending_item.meta = {}
                    pending_item.meta["download_error"] = str(exc)
                    # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
                    await manager.broadcast("task_error", {
                        "video_id": pending_item.id, "error": str(exc),
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                        "title": pending_item.title,
                    })
                    # 与 WebController _apply_video_state 对齐：失败时 video_state_changed 包含 local_path 和 content_type
                    await manager.broadcast("video_state_changed", {
                        "video_id": pending_item.id, "status": "❌ 失败", "progress": 0,
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                    })
                    await manager.broadcast("log", {"message": f"❌ 下载参数错误: {exc}"})
                    return
                except Exception as exc:
                    # 与 SDK 返回 error 结果路径对齐：保留 pending_item，设置 "❌ 失败" 状态和 download_error
                    # （不删除 pending_item，与 GUI _on_download_error 行为一致：失败条目保留在列表中可见）
                    pending_item.status = "❌ 失败"
                    pending_item.progress = 0
                    if pending_item.meta is None:
                        pending_item.meta = {}
                    pending_item.meta["download_error"] = f"下载失败: {exc}"
                    # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
                    await manager.broadcast("task_error", {
                        "video_id": pending_item.id, "error": f"下载失败: {exc}",
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                        "title": pending_item.title,
                    })
                    # 与 WebController _apply_video_state 对齐：失败时 video_state_changed 包含 local_path 和 content_type
                    await manager.broadcast("video_state_changed", {
                        "video_id": pending_item.id, "status": "❌ 失败", "progress": 0,
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                    })
                    await manager.broadcast("log", {"message": f"❌ 下载失败: {exc}"})
                    return
                finally:
                    # 防御性处理：确保 sdk 存在后再 close
                    try:
                        sdk.close()
                    except Exception:
                        pass

                # 就地更新 pending_item 属性，保持 video_id 一致（避免前端收到两个不同的 video_id）
                # 与 GUI _on_task_finished/_on_task_error 对齐：更新 item 状态
                if result.get("status") == "ok":
                    pending_item.status = "✅ 完成"
                    pending_item.progress = 100
                    local_path = result.get("local_path", "")
                    if local_path:
                        pending_item.local_path = local_path
                    pending_item.title = result.get("title", pending_item.title)
                    if pending_item.meta is None:
                        pending_item.meta = {}
                    content_type = result.get("content_type", "")
                    # 与 GUI spider 结果对齐：SDK 已通过 infer_content_type 推断 content_type，
                    # 若仍为空则从 pending_item.local_path 二次推断（防御性兜底）
                    if not content_type and local_path:
                        from cli.defaults import infer_content_type
                        content_type = infer_content_type(local_path)
                        result["content_type"] = content_type
                    if content_type:
                        pending_item.meta["content_type"] = content_type
                    pending_item.meta.update(result.get("meta", {}))
                    # 与 REST API /api/download 对齐：task_finished 包含完整信息
                    await manager.broadcast("task_finished", {
                        "video_id": pending_item.id,
                        "local_path": local_path,
                        "content_type": content_type,
                        "title": pending_item.title,
                    })
                    # 与 REST API /api/download 对齐：video_state_changed 包含 local_path 和 content_type
                    await manager.broadcast("video_state_changed", {
                        "video_id": pending_item.id,
                        "status": "✅ 完成",
                        "progress": 100,
                        "local_path": local_path,
                        "content_type": content_type,
                    })
                    await manager.broadcast("log", {"message": f"✅ 下载完成: {pending_item.title}"})
                else:
                    error_msg = result.get("error", "下载失败")
                    # 与 GUI/CLI 对齐：区分 "❌ 超时" 和 "❌ 失败"
                    if result.get("status") == "timeout" or "超时" in error_msg:
                        pending_item.status = "❌ 超时"
                    else:
                        pending_item.status = "❌ 失败"
                    pending_item.progress = 0
                    if pending_item.meta is None:
                        pending_item.meta = {}
                    pending_item.meta["download_error"] = error_msg
                    # 与成功路径对齐：从 SDK 结果更新 pending_item 属性
                    if result.get("local_path"):
                        pending_item.local_path = result["local_path"]
                    if result.get("title"):
                        pending_item.title = result["title"]
                    if result.get("meta") and isinstance(result["meta"], dict):
                        pending_item.meta.update(result["meta"])
                    # 与 WebController _on_task_error 对齐：task_error 包含 local_path/content_type/title
                    await manager.broadcast("task_error", {
                        "video_id": pending_item.id, "error": error_msg,
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                        "title": pending_item.title,
                    })
                    # 与 WebController _apply_video_state 对齐：失败/超时时 video_state_changed 包含 local_path 和 content_type
                    await manager.broadcast("video_state_changed", {
                        "video_id": pending_item.id, "status": pending_item.status, "progress": 0,
                        "local_path": pending_item.local_path or "",
                        "content_type": pending_item.meta.get("content_type", "") if pending_item.meta else "",
                    })
                    await manager.broadcast("log", {"message": f"❌ 下载失败: {error_msg}"})
        except Exception as exc:
            logging.error(f"[WS] 处理消息 {msg_type} 失败: {exc}", exc_info=True)
            # 尝试通过 WebSocket 推送错误信息给前端
            try:
                await manager.broadcast("log", {"message": f"❌ 处理 {msg_type} 失败: {exc}"})
            except Exception:
                pass

    # ---- 静态文件 ----

    @app.get("/")
    async def serve_index():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"error": "index.html not found"}

    # 挂载静态目录（放在最后，避免覆盖 API 路由）
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
