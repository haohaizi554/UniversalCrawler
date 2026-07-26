"""Read-only media health diagnostics backed by ffprobe."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.downloaders.external import (
    ExternalToolRunner,
    build_hidden_startupinfo,
    build_no_window_flags,
)
from app.core.tools.contracts import ToolContext, ToolManifest, ToolRunResult
from app.services.media_metadata_service import MediaMetadataService


_PARAMETERS = {
    "path": {
        "type": "file",
        "title": "媒体文件",
        "description": "要检查的本地媒体文件路径",
        "required": True,
    }
}


def _build_manifest() -> ToolManifest:
    return ToolManifest(
        id="media_health",
        title="媒体健康检查",
        summary="使用 ffprobe 只读检查本地媒体，并给出安全的修复建议",
        category="media",
        input_schema=_PARAMETERS,
        permissions=("read_file",),
        supports_cancel=True,
        icon="metadata",
        sort_order=30,
    )


def _build_result(
    status: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    error_code: str = "",
) -> ToolRunResult:
    payload = dict(data or {})
    if error_code:
        payload.setdefault("error_code", error_code)
    if status == "success":
        return ToolRunResult.success(message, data=payload)
    if status == "cancelled":
        return ToolRunResult.cancelled(message)
    return ToolRunResult.failure(message, data=payload)


def _context_inputs(context: ToolContext) -> Mapping[str, Any]:
    for name in (
        "parameters",
        "inputs",
        "input",
        "arguments",
        "params",
        "options",
        "data",
        "payload",
    ):
        value = getattr(context, name, None)
        if isinstance(value, Mapping):
            return value
    if isinstance(context, Mapping):
        return context
    return {}


def _raw_context_path(context: ToolContext) -> str:
    inputs = _context_inputs(context)
    for name in ("path", "file_path", "source_path", "media_path"):
        value = inputs.get(name)
        if value is not None:
            return str(value).strip()
    for name in ("path", "file_path", "source_path", "media_path"):
        value = getattr(context, name, None)
        if value is not None:
            return str(value).strip()
    return ""


def _context_path(context: ToolContext) -> str:
    path = _raw_context_path(context)
    if not path:
        return ""

    candidate = Path(path).expanduser()
    workspace_root = getattr(context, "workspace_root", None)
    if workspace_root is not None and not candidate.is_absolute():
        candidate = Path(workspace_root).expanduser() / candidate
    return str(candidate)


def _is_cancelled(context: ToolContext) -> bool:
    for name in ("cancel_event", "cancellation_event", "stop_event", "cancellation_token"):
        token = getattr(context, name, None)
        is_set = getattr(token, "is_set", None)
        if callable(is_set) and is_set():
            return True
        cancelled = getattr(token, "cancelled", None)
        if callable(cancelled) and cancelled():
            return True
        if isinstance(cancelled, bool) and cancelled:
            return True

    for name in ("is_cancelled", "cancelled", "should_cancel", "cancel_check"):
        value = getattr(context, name, None)
        if callable(value):
            if value():
                return True
        elif isinstance(value, bool) and value:
            return True
    return False


def _suggestion(code: str, title: str, description: str, command: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "title": title,
        "description": description,
    }
    if command:
        result["command_preview"] = command
    return result


def _remux_suggestion(path: str) -> dict[str, Any]:
    return _suggestion(
        "remux",
        "尝试无损重封装",
        "先保留源文件，使用 ffmpeg 复制音视频流到新文件以重建容器索引。",
        [
            "ffmpeg",
            "-i",
            path,
            "-map",
            "0",
            "-c",
            "copy",
            "<new-output-file>",
        ],
    )


class MediaHealthTool:
    """Diagnose one local media file without modifying it."""

    manifest = _build_manifest()

    def __init__(
        self,
        *,
        ffprobe_resolver: Callable[[], str | None] | None = None,
        process_factory: Callable[..., subprocess.Popen] | None = None,
        timeout_seconds: float = 15.0,
        poll_interval: float = 0.05,
    ) -> None:
        self._ffprobe_resolver = ffprobe_resolver or (
            lambda: ExternalToolRunner.resolve_executable(
                "ffprobe.exe",
                "ffprobe",
                ["-version"],
            )
        )
        self._process_factory = process_factory or subprocess.Popen
        self._timeout_seconds = max(0.1, float(timeout_seconds))
        self._poll_interval = max(0.0, float(poll_interval))

    def validate(self, context: ToolContext) -> list[str]:
        """Validate syntax only; filesystem checks belong to the worker run."""
        path = _raw_context_path(context)
        if not path:
            return ["请选择要检查的本地媒体文件"]
        parsed = urlparse(path)
        if parsed.scheme.lower() in {"http", "https", "ftp", "rtsp", "rtmp"}:
            return ["媒体健康检查仅支持本地文件"]
        return []

    def run(self, context: ToolContext) -> ToolRunResult:
        if _is_cancelled(context):
            return self._cancelled_result()

        errors = self.validate(context)
        if errors:
            return _build_result(
                "error",
                errors[0],
                data={"status": "invalid", "issues": [], "repair_suggestions": []},
                error_code="invalid_input",
            )

        path = _context_path(context)
        if threading.current_thread() is not threading.main_thread():
            return self._run_in_worker(context, path)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-health")
        future = executor.submit(self._run_in_worker, context, path)
        try:
            return self._await_worker(future)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def _await_worker(self, future: Future[ToolRunResult]) -> ToolRunResult:
        while True:
            try:
                return future.result(timeout=max(0.01, self._poll_interval))
            except FutureTimeoutError:
                continue

    def _run_in_worker(self, context: ToolContext, path_text: str) -> ToolRunResult:
        if _is_cancelled(context):
            return self._cancelled_result()

        path = Path(path_text).expanduser()
        authorizer = getattr(context, "authorize_path", None)
        if callable(authorizer):
            try:
                path = Path(authorizer(path))
            except PermissionError:
                return _build_result(
                    "error",
                    "媒体文件不在已批准的读取目录内",
                    data={
                        "status": "unavailable",
                        "path": str(path),
                        "issues": [],
                        "repair_suggestions": [],
                    },
                    error_code="path_not_authorized",
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                return _build_result(
                    "error",
                    "无法验证媒体文件路径",
                    data={
                        "status": "unavailable",
                        "path": str(path),
                        "detail": str(exc),
                        "issues": [],
                        "repair_suggestions": [],
                    },
                    error_code="invalid_path",
                )
        try:
            if not path.is_file():
                return _build_result(
                    "error",
                    "媒体文件不存在或不是普通文件",
                    data={
                        "status": "unavailable",
                        "path": str(path),
                        "issues": [],
                        "repair_suggestions": [],
                    },
                    error_code="file_not_found",
                )
            file_size = path.stat().st_size
        except OSError as exc:
            return _build_result(
                "error",
                "无法读取媒体文件信息",
                data={
                    "status": "unavailable",
                    "path": str(path),
                    "detail": str(exc),
                    "issues": [],
                    "repair_suggestions": [],
                },
                error_code="file_unreadable",
            )

        if file_size <= 0:
            return _build_result(
                "success",
                "检查完成：文件为空",
                data={
                    "status": "unhealthy",
                    "path": str(path),
                    "metadata": {"size_bytes": 0, "stream_count": 0},
                    "issues": [
                        {
                            "code": "empty_file",
                            "severity": "error",
                            "message": "文件大小为 0，无法包含有效媒体流。",
                        }
                    ],
                    "repair_suggestions": [
                        _suggestion(
                            "restore_source",
                            "重新获取源文件",
                            "空文件无法通过重封装修复，请从可信来源重新下载或恢复备份。",
                        )
                    ],
                },
            )

        if _is_cancelled(context):
            return self._cancelled_result(path=str(path))

        try:
            executable = self._ffprobe_resolver()
        except (OSError, subprocess.SubprocessError) as exc:
            return self._external_tool_failure(str(path), "ffprobe_start_failed", str(exc))
        if not executable:
            return self._external_tool_failure(str(path), "ffprobe_not_found")

        command = [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            process = self._process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=build_hidden_startupinfo(),
                creationflags=build_no_window_flags(),
                shell=False,
            )
        except FileNotFoundError:
            return self._external_tool_failure(str(path), "ffprobe_not_found")
        except (OSError, subprocess.SubprocessError) as exc:
            return self._external_tool_failure(str(path), "ffprobe_start_failed", str(exc))

        deadline = time.monotonic() + self._timeout_seconds
        stdout = ""
        stderr = ""
        communicated = False
        try:
            while process.poll() is None:
                if _is_cancelled(context):
                    ExternalToolRunner.terminate_process(process)
                    self._communicate_safely(process)
                    return self._cancelled_result(path=str(path))
                if time.monotonic() >= deadline:
                    ExternalToolRunner.terminate_process(process)
                    _stdout, stderr = self._communicate_safely(process)
                    return _build_result(
                        "error",
                        "ffprobe 检查超时",
                        data={
                            "status": "unavailable",
                            "path": str(path),
                            "detail": self._error_detail(stderr),
                            "issues": [],
                            "repair_suggestions": [],
                        },
                        error_code="probe_timeout",
                    )
                wait_timeout = min(
                    max(0.01, self._poll_interval),
                    max(0.01, deadline - time.monotonic()),
                )
                try:
                    stdout, stderr = process.communicate(timeout=wait_timeout)
                    stdout, stderr = str(stdout or ""), str(stderr or "")
                    communicated = True
                    break
                except subprocess.TimeoutExpired:
                    continue
            if not communicated:
                stdout, stderr = self._communicate_safely(process)
        except (OSError, subprocess.SubprocessError) as exc:
            ExternalToolRunner.terminate_process(process)
            return self._external_tool_failure(str(path), "probe_failed", str(exc))

        if _is_cancelled(context):
            return self._cancelled_result(path=str(path))

        returncode = int(process.returncode or 0)
        if returncode != 0:
            detail = self._error_detail(stderr) or f"ffprobe 退出码 {returncode}"
            return _build_result(
                "success",
                "检查完成：媒体文件无法正常解析",
                data={
                    "status": "unhealthy",
                    "path": str(path),
                    "metadata": {"size_bytes": file_size, "stream_count": 0},
                    "issues": [
                        {
                            "code": "probe_failed",
                            "severity": "error",
                            "message": f"ffprobe 无法解析文件：{detail}",
                        }
                    ],
                    "repair_suggestions": [_remux_suggestion(str(path))],
                },
            )

        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            return self._invalid_probe_result(str(path), str(exc))
        if not isinstance(payload, dict):
            return self._invalid_probe_result(str(path))
        format_payload = payload.get("format")
        stream_payload = payload.get("streams")
        if format_payload is not None and not isinstance(format_payload, Mapping):
            return self._invalid_probe_result(str(path), "format 字段不是对象")
        if stream_payload is not None and (
            not isinstance(stream_payload, list)
            or any(not isinstance(stream, Mapping) for stream in stream_payload)
        ):
            return self._invalid_probe_result(str(path), "streams 字段不是对象列表")

        return self._diagnose_payload(str(path), file_size, payload, stderr)

    @staticmethod
    def _communicate_safely(process: subprocess.Popen) -> tuple[str, str]:
        try:
            stdout, stderr = process.communicate(timeout=2)
        except (OSError, subprocess.SubprocessError):
            return "", ""
        return str(stdout or ""), str(stderr or "")

    def _diagnose_payload(
        self,
        path: str,
        file_size: int,
        payload: dict[str, Any],
        stderr: str,
    ) -> ToolRunResult:
        metadata = MediaMetadataService.from_ffprobe_payload(payload, path=path)
        format_payload = payload.get("format")
        format_data = format_payload if isinstance(format_payload, Mapping) else {}
        raw_streams = payload.get("streams")
        streams = [stream for stream in raw_streams or [] if isinstance(stream, Mapping)]
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if metadata.content_type == "image":
            content_type = "image"
        elif audio_streams and not video_streams:
            content_type = "audio"
        else:
            content_type = metadata.content_type

        reported_size = self._as_non_negative_int(format_data.get("size"))
        bit_rate = self._as_non_negative_int(format_data.get("bit_rate"))
        result_metadata = {
            "duration": metadata.duration,
            "resolution": metadata.resolution,
            "format": metadata.format,
            "content_type": content_type,
            "size_bytes": reported_size or file_size,
            "bit_rate": bit_rate,
            "stream_count": len(streams),
            "video_codec": str(video_streams[0].get("codec_name") or "") if video_streams else "",
            "audio_codec": str(audio_streams[0].get("codec_name") or "") if audio_streams else "",
        }

        issues: list[dict[str, str]] = []
        suggestions: list[dict[str, Any]] = []
        if not video_streams and not audio_streams:
            issues.append(
                {
                    "code": "no_media_streams",
                    "severity": "error",
                    "message": "未检测到可播放的音频或视频流。",
                }
            )
            suggestions.append(
                _suggestion(
                    "restore_source",
                    "检查或重新获取源文件",
                    "确认文件不是下载中的临时文件；若下载已结束，请重新获取源文件。",
                )
            )
        if content_type != "image" and (video_streams or audio_streams) and not metadata.duration:
            issues.append(
                {
                    "code": "missing_duration",
                    "severity": "warning",
                    "message": "容器没有可用的时长信息，拖动播放位置可能异常。",
                }
            )
            suggestions.append(_remux_suggestion(path))
        if video_streams and not metadata.resolution:
            issues.append(
                {
                    "code": "missing_video_dimensions",
                    "severity": "warning",
                    "message": "视频流缺少有效的宽高信息。",
                }
            )
            suggestions.append(
                _suggestion(
                    "reencode_video",
                    "考虑转码到新文件",
                    "保留源文件，并尝试将视频转码到常见编码与容器。",
                )
            )
        warning = self._error_detail(stderr)
        if warning:
            issues.append(
                {
                    "code": "probe_warning",
                    "severity": "warning",
                    "message": f"ffprobe 报告警告：{warning}",
                }
            )

        suggestions = self._deduplicate_suggestions(suggestions)
        if any(issue["severity"] == "error" for issue in issues):
            health_status = "unhealthy"
        elif issues:
            health_status = "warning"
        else:
            health_status = "healthy"
        message = {
            "healthy": "检查完成：媒体文件健康",
            "warning": "检查完成：发现可修复的媒体问题",
            "unhealthy": "检查完成：媒体文件可能不可播放",
        }[health_status]
        return _build_result(
            "success",
            message,
            data={
                "status": health_status,
                "path": path,
                "metadata": result_metadata,
                "issues": issues,
                "repair_suggestions": suggestions,
            },
        )

    @staticmethod
    def _deduplicate_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for suggestion in suggestions:
            code = str(suggestion.get("code") or "")
            if code in seen:
                continue
            seen.add(code)
            unique.append(suggestion)
        return unique

    @staticmethod
    def _as_non_negative_int(value: Any) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _error_detail(value: str) -> str:
        lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        return lines[-1][:500] if lines else ""

    @staticmethod
    def _invalid_probe_result(path: str, detail: str = "") -> ToolRunResult:
        data: dict[str, Any] = {
            "status": "unavailable",
            "path": path,
            "issues": [],
            "repair_suggestions": [],
        }
        if detail:
            data["detail"] = detail[:500]
        return _build_result(
            "error",
            "ffprobe 返回了无效数据",
            data=data,
            error_code="invalid_probe_output",
        )

    @staticmethod
    def _cancelled_result(*, path: str = "") -> ToolRunResult:
        data: dict[str, Any] = {
            "status": "cancelled",
            "issues": [],
            "repair_suggestions": [],
        }
        if path:
            data["path"] = path
        return _build_result(
            "cancelled",
            "媒体健康检查已取消",
            data=data,
            error_code="cancelled",
        )

    @staticmethod
    def _external_tool_failure(path: str, error_code: str, detail: str = "") -> ToolRunResult:
        if error_code == "ffprobe_not_found":
            message = "未找到 ffprobe，无法检查媒体文件"
        else:
            message = "无法启动 ffprobe"
        data: dict[str, Any] = {
            "status": "unavailable",
            "path": path,
            "issues": [],
            "repair_suggestions": [
                _suggestion(
                    "install_ffmpeg",
                    "安装或恢复 FFmpeg 工具",
                    "请确认项目目录包含 ffprobe，或系统 PATH 中可执行 ffprobe。",
                )
            ],
        }
        if detail:
            data["detail"] = detail[:500]
        return _build_result(
            "error",
            message,
            data=data,
            error_code=error_code,
        )


TOOL = MediaHealthTool()
tool = TOOL
manifest = TOOL.manifest


def validate(context: ToolContext) -> list[str]:
    return TOOL.validate(context)


def run(context: ToolContext) -> ToolRunResult:
    return TOOL.run(context)


__all__ = ["MediaHealthTool", "TOOL", "manifest", "run", "tool", "validate"]
