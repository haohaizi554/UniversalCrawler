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
            return RuleSelection(
                select=selection_dict.get("select"),
                exclude=selection_dict.get("exclude"),
                all_items=selection_dict.get("all_items", False),
                first=selection_dict.get("first", False),
                last=selection_dict.get("last", False),
            )
        elif strategy == "preload":
            choices = selection_dict.get("choices", [])
            return PipeSelection(preloaded_choices=choices)
        else:
            return RuleSelection(all_items=True)

    @app.get("/api/ping")
    async def ping():
        return {"status": "ok", "version": "v19-fix"}

    @app.get("/api/platforms")
    async def get_platforms():
        return controller.get_platforms()

    @app.get("/api/config")
    async def get_config():
        return controller.get_config()

    @app.put("/api/config")
    async def update_config(updates: dict):
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

        try:
            controller.current_save_dir = directory
            controller.videos.clear()
            scan_limit = cfg.get("download", "local_scan_limit", 1000)
            try:
                scan_limit = int(scan_limit)
            except (ValueError, TypeError):
                scan_limit = 1000

            result = await asyncio.get_running_loop().run_in_executor(
                None, controller.file_service.scan_directory, directory, scan_limit,
            )

            items = []
            for item in result.items:
                controller.videos[item.id] = item
                try:
                    items.append(controller._video_item_to_dict(item))
                except Exception:
                    items.append({"id": item.id, "title": getattr(item, 'title', ''), "url": "", "source": "", "status": "", "progress": 0, "local_path": getattr(item, 'local_path', ''), "content_type": "", "meta": {}})

            msg = f"已加载 {result.total_count} 个本地文件 (视频: {result.video_count}, 图片: {result.image_count})"
            if result.truncated:
                msg = f"文件过多 ({result.original_count}个)，仅加载最新的 {result.total_count} 个。"
            elif result.total_count == 0:
                msg = "该目录下没有找到视频或图片"

            return {
                "status": "ok", "directory": directory, "items": items,
                "total_count": result.total_count, "video_count": result.video_count,
                "image_count": result.image_count, "message": msg,
            }
        except Exception as exc:
            logger.error(f"[scan] 扫描失败: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc)}

    @app.post("/api/search")
    async def search(body: dict):
        """同步搜索端点：使用 CLIRunner，输入输出与 CLI/SDK 完全一致。

        与 GUI ApplicationController 的行为对齐：
        1. 创建 spider（同 GUI _create_spider）
        2. monkey-patch ask_user_selection（同 CLI CLIRunner）
        3. 绑定信号（同 GUI _bind_spider_signals）
        4. 等待 spider 完成 + 下载完成
        5. 返回完整结果（含最终 status/progress/local_path）

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
        if not source or not keyword:
            return {"status": "error", "error": "source 和 keyword 为必填参数"}

        save_dir = body.get("save_dir") or controller.current_save_dir
        config = body.get("config", {})
        selection_dict = body.get("selection")
        timeout = body.get("timeout")
        download = body.get("download", True)

        strategy = _build_selection_strategy(selection_dict)

        def _run_search():
            from cli.runner import CLIRunner
            runner = CLIRunner(
                source=source,
                keyword=keyword,
                save_dir=save_dir,
                selection_strategy=strategy,
                config=config,
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
        config = body.get("config", {})
        selection_dict = body.get("selection")

        # 如果提供了 selection 策略，存储到 controller 供 spider 使用
        if selection_dict:
            strategy = _build_selection_strategy(selection_dict)
            controller._pending_selection_strategy = strategy
        else:
            controller._pending_selection_strategy = None

        controller.start_crawl(source, keyword, config)
        return {"status": "ok"}

    @app.post("/api/crawl/stop")
    async def stop_crawl():
        controller.stop_crawl()
        return {"status": "ok"}

    @app.post("/api/crawl/select")
    async def select_tasks(body: dict):
        indices = body.get("indices", [])
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
        controller.delete_video(video_id)
        return {"status": "ok"}

    @app.post("/api/video/rename")
    async def rename_video(body: dict):
        video_id = body.get("video_id", "")
        new_title = body.get("new_title", "")
        result = controller.rename_video(video_id, new_title)
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
                controller.videos[item.id] = item
                try:
                    items.append(controller._video_item_to_dict(item))
                except Exception:
                    items.append({
                        "id": item.id, "title": getattr(item, 'title', ''),
                        "url": "", "source": "", "status": "", "progress": 0,
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
                controller.start_crawl(
                    data.get("source", ""),
                    data.get("keyword", ""),
                    data.get("config", {}),
                )
            elif msg_type == "stop_crawl":
                controller.stop_crawl()
            elif msg_type == "select_tasks":
                indices = data.get("indices")
                controller.resume_spider_selection(indices if indices is not None else None)
            elif msg_type == "scan_dir":
                await controller.async_scan_local_dir(data.get("directory"))
            elif msg_type == "change_dir":
                directory = data.get("directory", "")
                await controller.async_change_dir(directory)
            elif msg_type == "change_theme":
                is_dark = data.get("dark_theme", True)
                cfg.set("common", "dark_theme", is_dark)
                cfg.set("common", "theme", "dark" if is_dark else "light")
            elif msg_type == "change_source":
                cfg.set("common", "last_source", data.get("source", ""))
            elif msg_type == "save_config":
                section = data.get("section", "")
                key = data.get("key", "")
                value = data.get("value")
                if section and key:
                    try:
                        cfg.set(section, key, value)
                    except Exception:
                        pass
            elif msg_type == "delete_video":
                vid = data.get("video_id", "")
                await controller.async_delete_video(vid)
            elif msg_type == "rename_video":
                vid = data.get("video_id", "")
                title = data.get("new_title", "")
                await controller.async_rename_video(vid, title)
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
