"""Web 目录与本地媒体路由服务。"""

from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Callable

from fastapi import Request

from app.config import cfg
from app.web.api_result import error_result
from app.web.logging_utils import log_web_event, log_web_exception
from app.web.session_runtime import WebSessionContext, is_local_host

GetRequestContext = Callable[[Request], WebSessionContext]
RequireAllowedDirectory = Callable[[WebSessionContext, str], str]
MAX_SCAN_LIMIT = 5000

class WebDirectoryService:
    """承载目录浏览、扫描、切换与原生目录选择逻辑。"""

    def __init__(
        self,
        *,
        get_request_context: GetRequestContext,
        require_allowed_directory: RequireAllowedDirectory,
        native_folder_picker_enabled: bool = True,
    ) -> None:
        self._get_request_context = get_request_context
        self._require_allowed_directory = require_allowed_directory
        self._native_folder_picker_enabled = bool(native_folder_picker_enabled)

    async def scan_directory(self, request: Request, body: dict | None = None) -> dict:
        context = self._get_request_context(request)
        session_controller = context.controller
        body = body if isinstance(body, dict) else await self._parse_request_json(request, action="scan_directory")

        directory = body.get("directory") or session_controller.current_save_dir
        if not directory:
            return error_result("目录路径不能为空")
        if not isinstance(directory, str):
            return error_result("directory 必须是字符串")
        null_byte_error = self._validate_path_text(directory)
        if null_byte_error is not None:
            return null_byte_error

        try:
            directory = self._require_allowed_directory(context, directory)
        except PermissionError as exc:
            return error_result(str(exc), http_status=403)

        scan_limit = body.get("scan_limit")
        if scan_limit is not None:
            if not isinstance(scan_limit, int):
                return error_result("scan_limit 必须是整数")
            if scan_limit <= 0:
                return error_result("scan_limit 必须大于 0")
            if scan_limit > MAX_SCAN_LIMIT:
                return error_result(f"scan_limit 不能大于 {MAX_SCAN_LIMIT}")
        if scan_limit is None:
            scan_limit = self._normalize_scan_limit(cfg.get("download", "local_scan_limit", 1000))

        try:
            self._clear_controller_videos(session_controller)
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                session_controller.file_service.scan_directory,
                directory,
                scan_limit,
            )
            items = self._build_local_media_items(session_controller, result.items)
            return self._build_scan_response(directory, result, items)
        except Exception as exc:
            log_web_exception("WebDirectoryService", "scan_directory", exc, context={"directory": directory})
            return error_result(str(exc), http_status=500, directory=directory)

    async def list_directory(self, request: Request, path: str = "") -> dict:
        context = self._get_request_context(request)
        session_controller = context.controller
        if not path:
            path = session_controller.current_save_dir
        null_byte_error = self._validate_path_text(path)
        if null_byte_error is not None:
            return null_byte_error

        try:
            path = self._require_allowed_directory(context, path)
        except PermissionError as exc:
            return error_result(str(exc), http_status=403, path=path)

        try:
            exists, subdirs = await asyncio.get_running_loop().run_in_executor(
                None,
                self._collect_subdirectories,
                path,
            )
            if not exists:
                return error_result("目录不存在", http_status=404, path=path)
            parent_candidate = os.path.dirname(path) if path else ""
            parent = parent_candidate if parent_candidate and context.is_directory_allowed(parent_candidate) else ""
            drives = [{"name": root, "path": root} for root in sorted(context.approved_roots_snapshot())]
            return {
                "current": path,
                "parent": parent,
                "subdirs": subdirs,
                "drives": drives,
            }
        except PermissionError:
            return error_result("无权限访问该目录", http_status=403, path=path)
        except OSError as exc:
            return error_result(str(exc), http_status=500, path=path)

    @staticmethod
    def _collect_subdirectories(path: str) -> tuple[bool, list[dict[str, str]]]:
        if not os.path.exists(path):
            return False, []
        subdirs: list[dict[str, str]] = []
        entries = os.listdir(path)
        for name in sorted(entries, key=str.lower):
            full = os.path.join(path, name)
            try:
                if os.path.isdir(full) and not name.startswith("."):
                    subdirs.append({"name": name, "path": full})
            except PermissionError:
                continue
        return True, subdirs

    async def change_dir(self, request: Request) -> dict:
        try:
            body = await self._parse_request_json(request, action="change_dir")

            context = self._get_request_context(request)
            session_controller = context.controller
            if not isinstance(body, dict):
                return error_result("请求体必须是 JSON 对象")

            directory = body.get("directory", "")
            if not directory:
                return error_result("目录路径不能为空")
            if not isinstance(directory, str):
                return error_result("directory 必须是字符串")
            null_byte_error = self._validate_path_text(directory)
            if null_byte_error is not None:
                return null_byte_error
            try:
                directory = self._require_allowed_directory(context, directory)
            except PermissionError as exc:
                return error_result(str(exc), http_status=403)

            log_web_event(
                "WebDirectoryService",
                "change_dir_start",
                "开始切换目录",
                context={"directory": directory},
            )
            session_controller.current_save_dir = directory

            def _save_cfg() -> None:
                try:
                    cfg.set("common", "save_directory", directory)
                except Exception as exc:
                    log_web_exception(
                        "WebDirectoryService",
                        "persist_save_directory",
                        exc,
                        context={"directory": directory},
                    )

            await asyncio.get_running_loop().run_in_executor(None, _save_cfg)
            self._clear_controller_videos(session_controller)

            scan_limit = self._normalize_scan_limit(cfg.get("download", "local_scan_limit", 1000))
            result = await asyncio.get_running_loop().run_in_executor(
                None,
                session_controller.file_service.scan_directory,
                directory,
                scan_limit,
            )
            log_web_event(
                "WebDirectoryService",
                "change_dir_scan_complete",
                "目录切换后的初始扫描完成",
                context={"directory": directory},
                details={"total_count": result.total_count},
            )

            items = self._build_local_media_items(session_controller, result.items)
            return self._build_scan_response(directory, result, items)
        except Exception as exc:
            log_web_exception("WebDirectoryService", "change_dir", exc)
            return error_result(str(exc), http_status=500)

    async def pick_native_folder(self, request: Request) -> dict:
        if not self._native_folder_picker_enabled:
            # Remote deployments can sit behind a loopback reverse proxy, so
            # client.host alone is not a sufficient trust signal in this mode.
            return error_result("native folder picker is disabled for remote deployments", http_status=403)
        client = getattr(request, "client", None)
        if not is_local_host(getattr(client, "host", None)):
            # This endpoint controls a modal dialog on the server desktop. A LAN
            # browser must never be able to display or spam native server UI.
            return error_result("native folder picker is available only on this device", http_status=403)
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(None, self._powershell_pick_dir)
            if path:
                normalized = self._get_request_context(request).approve_directory(path)
                return {"path": normalized}
            return {"path": ""}
        except Exception as exc:
            log_web_exception("WebDirectoryService", "pick_native_folder", exc)
            return {"error": str(exc)}

    @staticmethod
    async def _parse_request_json(request: Request, *, action: str) -> dict:
        try:
            body = await request.json()
        except Exception as exc:
            log_web_exception(
                "WebDirectoryService",
                "parse_request_json",
                exc,
                context={"action": action},
            )
            return {}
        if isinstance(body, dict):
            return body
        return body

    @staticmethod
    def _normalize_scan_limit(raw_limit) -> int:
        try:
            return max(1, min(int(raw_limit), MAX_SCAN_LIMIT))
        except (ValueError, TypeError):
            return 1000

    @staticmethod
    def _validate_path_text(path: str) -> dict | None:
        if "\x00" in path:
            return error_result("目录路径不能包含空字节", http_status=400)
        return None

    @staticmethod
    def _build_local_media_items(session_controller, items: list) -> list[dict]:
        normalized_items = []
        for item in items:
            item.status = "✅ 本地"
            item.progress = 100
            WebDirectoryService._store_controller_video(session_controller, item)
            try:
                normalized_items.append(session_controller._video_item_to_dict(item))
            except Exception as exc:
                log_web_exception(
                    "WebDirectoryService",
                    "build_local_media_items",
                    exc,
                    context={"item_id": getattr(item, "id", "")},
                    details={"fallback": True},
                )
                normalized_items.append(
                    {
                        "id": item.id,
                        "title": getattr(item, "title", ""),
                        "url": "",
                        "source": "",
                        "status": "✅ 本地",
                        "progress": 100,
                        "local_path": getattr(item, "local_path", ""),
                        "content_type": "",
                        "meta": {},
                    }
                )
        return normalized_items

    @staticmethod
    def _clear_controller_videos(session_controller) -> None:
        clear_videos = getattr(session_controller, "_clear_video_items", None)
        if callable(clear_videos):
            clear_videos()
            return
        session_controller.videos.clear()

    @staticmethod
    def _store_controller_video(session_controller, item) -> None:
        store_video = getattr(session_controller, "_store_video_item", None)
        if callable(store_video):
            store_video(item)
            return
        session_controller.videos[item.id] = item

    @staticmethod
    def _build_scan_response(directory: str, result, items: list[dict]) -> dict:
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

    @staticmethod
    def _powershell_pick_dir():
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
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=300,
            )
            path = result.stdout.strip()
            return path if path else None
        except subprocess.TimeoutExpired:
            return None
        except Exception as exc:
            log_web_exception("WebDirectoryService", "powershell_pick_dir", exc)
            return None
