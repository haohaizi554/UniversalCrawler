"""Web 文件响应服务。"""

from __future__ import annotations

import mimetypes
import os
import re
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.services.path_policy import PathPolicy

class WebFileResponseService:
    """承载媒体文件与调试产物的文件响应逻辑。"""

    MEDIA_TYPE_OVERRIDES = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
        ".ts": "video/mp2t",
        ".m3u8": "application/vnd.apple.mpegurl",
    }

    def __init__(
        self,
        *,
        get_request_context: Callable[[Request], object],
        has_valid_session_token: Callable[[Request], bool],
        path_policy: PathPolicy | None = None,
    ) -> None:
        self._get_request_context = get_request_context
        self._has_valid_session_token = has_valid_session_token
        self._path_policy = path_policy or PathPolicy()

    def _require_session_token(self, request: Request) -> None:
        if not self._has_valid_session_token(request):
            raise HTTPException(status_code=403, detail="缺少或无效的会话令牌")

    def _guess_media_type(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext in self.MEDIA_TYPE_OVERRIDES:
            return self.MEDIA_TYPE_OVERRIDES[ext]
        content_type, _ = mimetypes.guess_type(path)
        return content_type or "application/octet-stream"

    async def get_media(self, request: Request, video_id: str, range_header: str | None):
        self._require_session_token(request)
        context = self._get_request_context(request)
        path = context.controller.get_media_path(video_id)
        if not path:
            raise HTTPException(status_code=404, detail="file not found")
        try:
            path = self._path_policy.resolve_existing_file(path, context.approved_roots)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="file not found")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        file_size = os.path.getsize(path)
        content_type = self._guess_media_type(path)

        if range_header:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                chunk_size = end - start + 1

                async def stream_range():
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

        return FileResponse(
            path,
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    def latest_log_response(self, request: Request):
        self._require_session_token(request)
        from app.services.debug_service import DebugArtifactsService

        service = DebugArtifactsService()
        log_path = service.latest_log_path()
        if log_path and os.path.exists(log_path):
            return FileResponse(log_path, filename=os.path.basename(log_path), media_type="text/plain")
        return {"error": "日志文件不存在"}

    def latest_error_summary_response(self, request: Request):
        self._require_session_token(request)
        from app.services.debug_service import DebugArtifactsService

        service = DebugArtifactsService()
        summary_path = service.latest_error_summary_path()
        if summary_path and os.path.exists(summary_path):
            return FileResponse(summary_path, filename=os.path.basename(summary_path), media_type="text/markdown")
        return {"error": "错误摘要不存在"}
