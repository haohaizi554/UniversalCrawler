"""实现 `app/debug_logger.py` 对应功能的 Python 模块。"""

import json
import os
import re
import threading
import multiprocessing
import uuid
from datetime import datetime
from typing import Any

from app.utils.runtime_paths import user_logs_root


class DebugLogger:
    """统一调试日志记录器。

    目标：
    1. 面向调试，强调可读性，而不是纯 JSON 堆砌；
    2. 保留关键上下文，避免日志过长；
    3. 支持多线程写入；
    4. 默认写入项目根目录下的 logs 文件夹。
    """

    SENSITIVE_KEYS = {
        "cookie",
        "cookies",
        "cookie_str",
        "authorization",
        "access_token",
        "refresh_token",
        "token",
        "sessionid",
        "sessionid_ss",
        "sessdata",
        "password",
        "secret",
        "proxy_auth",
    }

    def __init__(self):
        """初始化当前实例并准备运行所需的状态，供 `DebugLogger` 使用。"""
        self.logs_dir = user_logs_root()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        process_name = multiprocessing.current_process().name
        # 修复 BUG-169: web 子进程和主进程区分开，避免 latest_debug.log 写冲突
        self._is_main_process = (process_name == "MainProcess")
        self.session_file = self.logs_dir / f"debug_{timestamp}_{process_name}.log"
        self.latest_file = self.logs_dir / "latest_debug.log"
        self.latest_error_summary_file = self.logs_dir / "latest_error_summary.md"
        self._lock = threading.Lock()

        # 仅主进程覆盖 latest_debug.log，避免 Windows 多进程扫码登录时冲掉主日志
        # 修复 BUG-169: 加 try/except 防止 web 进程并发清空文件时 PermissionError
        if self._is_main_process:
            self._safe_write_text(self.latest_file, "")
            self._safe_write_text(
                self.latest_error_summary_file,
                "# 最近错误摘要\n\n当前会话暂无错误。\n",
            )
        self._write_header()

    def _safe_write_text(self, path, content, encoding="utf-8"):
        """修复 BUG-169: write_text 加 try/except，避免 Windows 文件锁 PermissionError"""
        import time as _time
        for attempt in range(3):
            try:
                path.write_text(content, encoding=encoding)
                return True
            except (OSError, PermissionError) as exc:
                if attempt == 2:
                    # 3 次都失败，静默放弃（不影响爬虫主流程）
                    import logging
                    logging.getLogger(__name__).debug(
                        f"[debug_logger] 无法写入 {path.name}: {exc}"
                    )
                    return False
                _time.sleep(0.05 * (attempt + 1))  # 50ms / 100ms / 150ms 重试
        return False

    def _write_header(self):
        """提供 `_write_header` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        header = [
            "=" * 88,
            f"Universal Crawler Pro Debug Session",
            f"Started At : {self._now()}",
            f"Log File   : {self.session_file.name}",
            "=" * 88,
            "",
        ]
        self._append_lines(header)

    def _now(self) -> str:
        """提供 `_now` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _is_sensitive_key(self, key: str) -> bool:
        """提供 `_is_sensitive_key` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        lower_key = key.lower()
        if lower_key.endswith(("_path", "_file", "_dir")):
            return False
        if lower_key in self.SENSITIVE_KEYS:
            return True
        return any(
            marker in lower_key
            for marker in ("authorization", "sessionid", "sessdata", "password", "secret", "token")
        )

    def _mask_inline_secret(self, value: str) -> str:
        """提供 `_mask_inline_secret` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        masked = re.sub(
            r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@:\s]+)(?::([^@/\s]*))?@",
            r"\1***:***@",
            value,
        )
        masked = re.sub(
            r"([?&](?:token|access_token|refresh_token|sessionid(?:_ss)?|sessdata|mstoken|ttwid|authorization|cookie)=)[^&]+",
            r"\1***",
            masked,
            flags=re.IGNORECASE,
        )
        lowered = masked.lower()
        if lowered.startswith("bearer "):
            return "Bearer ***"
        if lowered.startswith("cookie:"):
            return "Cookie: [已脱敏]"
        if lowered.startswith("authorization:"):
            return "Authorization: [已脱敏]"
        return masked

    def _redact_sensitive_value(self, value: Any) -> Any:
        """提供 `_redact_sensitive_value` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        if isinstance(value, str):
            masked = self._mask_inline_secret(value)
            return masked if masked != value else "[已脱敏]"
        if isinstance(value, (dict, list, tuple, set)):
            return "[已脱敏]"
        return "***"

    def _append_lines(self, lines: list[str]):
        """提供 `_append_lines` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        content = "\n".join(lines) + "\n"
        import time as _time
        with self._lock:
            # 修复 BUG-169: session_file 每个进程独立，但仍加 try/except + 重试
            for attempt in range(3):
                try:
                    with open(self.session_file, "a", encoding="utf-8") as fp:
                        fp.write(content)
                    break
                except (OSError, PermissionError):
                    if attempt == 2:
                        # session_file 也写不进去时只放弃这一行，不抛异常
                        return
                    _time.sleep(0.05 * (attempt + 1))
            # 修复 BUG-169: latest_debug.log 只在主进程写，避免和 web 进程冲突
            if self._is_main_process:
                for attempt in range(3):
                    try:
                        with open(self.latest_file, "a", encoding="utf-8") as fp:
                            fp.write(content)
                        break
                    except (OSError, PermissionError):
                        if attempt == 2:
                            return
                        _time.sleep(0.05 * (attempt + 1))

    def _clean_mapping(self, data: dict[str, Any] | None) -> dict[str, Any]:
        """提供 `_clean_mapping` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        if not data:
            return {}
        cleaned = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
                continue
            if self._is_sensitive_key(str(key)):
                cleaned[key] = self._redact_sensitive_value(value)
                continue
            if isinstance(value, str):
                cleaned[key] = self._mask_inline_secret(value)
                continue
            cleaned[key] = value
        return cleaned

    def _format_mapping(self, title: str, data: dict[str, Any] | None) -> list[str]:
        """提供 `_format_mapping` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        data = self._clean_mapping(data)
        if not data:
            return []
        lines = [f"{title}:"]
        for key, value in data.items():
            normalized = self._normalize_value(value)
            if isinstance(normalized, dict):
                lines.append(f"  - {key}:")
                for sub_key, sub_value in normalized.items():
                    lines.append(f"      {sub_key}: {sub_value}")
            elif isinstance(normalized, list):
                lines.append(f"  - {key}: {', '.join(str(i) for i in normalized)}")
            else:
                lines.append(f"  - {key}: {normalized}")
        return lines

    def _normalize_value(self, value: Any) -> Any:
        """提供 `_normalize_value` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        if isinstance(value, dict):
            result = {}
            for key, item in list(value.items())[:20]:
                normalized = (
                    self._redact_sensitive_value(item)
                    if self._is_sensitive_key(str(key))
                    else self._normalize_value(item)
                )
                if normalized in (None, "", [], {}):
                    continue
                result[str(key)] = normalized
            return result
        if isinstance(value, (list, tuple, set)):
            items = list(value)[:10]
            normalized = [self._normalize_value(item) for item in items]
            if len(value) > 10:
                normalized.append(f"... 共 {len(value)} 项")
            return normalized
        if isinstance(value, str):
            cleaned = self._mask_inline_secret(value.replace("\n", " ").replace("\r", " ").strip())
            if len(cleaned) > 220:
                return cleaned[:217] + "..."
            return cleaned
        return value

    def new_trace_id(self, prefix: str = "trace") -> str:
        """执行 `new_trace_id` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        stamp = datetime.now().strftime("%H%M%S")
        short = uuid.uuid4().hex[:8]
        return f"{prefix}-{stamp}-{short}"

    def pick_used(self, source: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
        """执行 `pick_used` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        if not source:
            return {}
        return self._clean_mapping({key: source.get(key) for key in keys if key in source})

    def _write_error_summary(
        self,
        component: str,
        action: str,
        message: str,
        status_code: int | str | None,
        trace_id: str | None,
        context: dict[str, Any] | None,
        details: dict[str, Any] | None,
    ):
        # 错误摘要始终覆盖为“最近一次错误”，这样用户从 UI 打开时能直接看到最新诊断结论。
        """提供 `_write_error_summary` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        severity = self._infer_error_severity(component, action, status_code, details)
        conclusion = self._build_error_conclusion(component, action, status_code, details)
        suggestions = self._build_error_suggestions(component, action, status_code, details)
        lines = [
            "# 最近错误摘要",
            "",
            f"- 时间: {self._now()}",
            f"- 模块: {component}",
            f"- 动作: {action}",
            f"- 状态码: {status_code or '未提供'}",
            f"- 错误分级: {severity}",
            f"- 追踪ID: {trace_id or '未提供'}",
            f"- 错误说明: {message or '未提供'}",
            "",
        ]
        lines.append("## 自动建议结论")
        lines.append(f"- {conclusion}")
        lines.append("")
        if self._clean_mapping(context):
            lines.append("## 上下文")
            for key, value in self._clean_mapping(context).items():
                lines.append(f"- {key}: {self._normalize_value(value)}")
            lines.append("")
        if self._clean_mapping(details):
            lines.append("## 关键详情")
            for key, value in self._clean_mapping(details).items():
                lines.append(f"- {key}: {self._normalize_value(value)}")
            lines.append("")
        lines.append("## 优先排查")
        for item in suggestions:
            lines.append(f"- {item}")
        lines.append("")
        with self._lock:
            # 修复 BUG-169: error_summary 也加 try/except + 重试
            self._safe_write_text(self.latest_error_summary_file, "\n".join(lines))

    def _infer_error_severity(
        self,
        component: str,
        action: str,
        status_code: int | str | None,
        details: dict[str, Any] | None,
    ) -> str:
        # 这里做的是“面向排障”的粗粒度优先级分类，不追求精确异常学术定义。
        """提供 `_infer_error_severity` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        text = f"{component} {action} {status_code or ''} {json.dumps(self._normalize_value(details or {}), ensure_ascii=False)}".lower()
        if "stop" in text or "用户停止" in text:
            return "P4-用户操作"
        if "permission" in text or "权限" in text or "file not found" in text or "未找到" in text:
            return "P1-阻断"
        if "ffmpeg" in text or "n_m3u8dl" in text or "merge" in text:
            return "P2-高"
        if "api" in action.lower() or "bili" in text or "douyin" in text or "kuaishou" in text or "missav" in text:
            return "P2-高"
        if "download" in text:
            return "P2-高"
        return "P3-中"

    def _build_error_conclusion(
        self,
        component: str,
        action: str,
        status_code: int | str | None,
        details: dict[str, Any] | None,
    ) -> str:
        """提供 `_build_error_conclusion` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        text = f"{component} {action} {status_code or ''} {json.dumps(self._normalize_value(details or {}), ensure_ascii=False)}".lower()
        if "ffmpeg" in text:
            return "问题大概率出在 ffmpeg 执行或合并阶段，优先核对输入 URL、Referer、输出路径和 ffmpeg 是否可用。"
        if "n_m3u8dl" in text or "m3u8" in text:
            return "问题大概率出在 HLS 流下载阶段，优先核对 m3u8 地址、Referer、User-Agent 和保存目录权限。"
        if "bili" in text:
            return "问题大概率出在 Bilibili 接口取流或音视频流下载阶段，建议先检查 get_play_url 和 stream_* 记录。"
        if "douyin" in text:
            return "问题大概率出在抖音详情解析或资源下载阶段，建议先检查 detail / search / account 和 DouyinDownloader 记录。"
        if "kuaishou" in text:
            return "问题大概率出在快手视频流捕获或下载阶段，建议先检查资源捕获日志和最终提交的下载 URL。"
        if "missav" in text:
            return "问题大概率出在 MissAV 页面嗅探或 m3u8 提交阶段，建议先检查 playlist.m3u8 嗅探结果和下载参数。"
        if "downloadworker" in text or "downloadmanager" in text:
            return "问题大概率出在任务入队、分发或下载线程执行阶段，建议按 DL_QUEUE 到 DL_START 的链路逆向排查。"
        return "问题位置需要结合追踪ID继续查看相邻的 API、COMMAND 和下载记录来判断。"

    def _build_error_suggestions(
        self,
        component: str,
        action: str,
        status_code: int | str | None,
        details: dict[str, Any] | None,
    ) -> list[str]:
        """提供 `_build_error_suggestions` 对应的内部辅助逻辑，供 `DebugLogger` 使用。"""
        detail_text = json.dumps(self._normalize_value(details or {}), ensure_ascii=False)
        suggestions = [
            "先用追踪ID在 latest_debug.log 中全文搜索，查看同一任务前后的 API、入队、下载和合并记录。",
        ]
        if "Bili" in component or "BILI" in str(status_code):
            suggestions.append("重点检查 `API::get_play_url`、`stream_video`、`stream_audio` 和 `ffmpeg` 记录是否连续。")
            suggestions.append("如果是播放流失败，优先确认 `audio_url/video_url` 是否为空、Cookie 是否失效、画质是否受限。")
        if "Douyin" in component or "DOUYIN" in str(status_code):
            suggestions.append("重点检查 `API::detail`、`API::account_page`、`API::search_page` 和 `DouyinDownloader` 的记录。")
            suggestions.append("如果是下载失败，优先确认资源链接是否过期，以及 Cookie/Referer 是否仍有效。")
        if "ffmpeg" in component.lower() or "ffmpeg" in detail_text.lower():
            suggestions.append("查看 ffmpeg 参数块，确认输入 URL、Referer、输出路径是否正确。")
        if "N_m3u8DL" in component or "m3u8" in detail_text.lower():
            suggestions.append("查看 N_m3u8DL-RE 参数块，确认 m3u8 链接、保存目录、User-Agent 和 Referer 是否正确。")
        if "DownloadWorker" in component or "DownloadManager" in component:
            suggestions.append("从 `DL_QUEUE -> DL_DISPATCH -> DL_START -> 下载器记录` 这一条链路逆向定位。")
        if len(suggestions) < 3:
            suggestions.append("结合模块名和状态码，继续查看同时间附近的上一条 API 或 COMMAND 记录。")
        return suggestions

    def log(
        self,
        component: str,
        action: str,
        level: str = "INFO",
        message: str = "",
        status_code: int | str | None = None,
        context: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ):
        """执行 `log` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        context = self._clean_mapping(context)
        details = self._clean_mapping(details)
        lines = [
            "-" * 88,
            f"[{self._now()}] [{level.upper()}] {component} / {action}",
        ]
        if message:
            lines.append(f"说明: {message}")
        if status_code is not None:
            lines.append(f"状态码: {status_code}")
        if trace_id:
            lines.append(f"追踪ID: {trace_id}")
        lines.extend(self._format_mapping("上下文", context))
        lines.extend(self._format_mapping("详情", details))
        lines.append("")
        self._append_lines(lines)
        if level.upper() == "ERROR":
            self._write_error_summary(component, action, message, status_code, trace_id, context, details)

    def log_api(
        self,
        component: str,
        api_name: str,
        request: dict[str, Any] | None = None,
        response_summary: dict[str, Any] | None = None,
        level: str = "INFO",
        message: str = "",
        status_code: int | str | None = None,
        trace_id: str | None = None,
    ):
        """执行 `log_api` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        request = self._clean_mapping(request)
        response_summary = self._clean_mapping(response_summary)
        lines = [
            "-" * 88,
            f"[{self._now()}] [{level.upper()}] {component} / API::{api_name}",
        ]
        if message:
            lines.append(f"说明: {message}")
        if status_code is not None:
            lines.append(f"状态码: {status_code}")
        if trace_id:
            lines.append(f"追踪ID: {trace_id}")
        lines.extend(self._format_mapping("请求", request))
        lines.extend(self._format_mapping("响应摘要", response_summary))
        lines.append("")
        self._append_lines(lines)
        if level.upper() == "ERROR":
            self._write_error_summary(component, f"API::{api_name}", message, status_code, trace_id, request, response_summary)

    def log_command(
        self,
        component: str,
        tool_name: str,
        command_args: list[str] | tuple[str, ...] | None = None,
        message: str = "",
        context: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ):
        """执行 `log_command` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        details = {}
        if command_args:
            details["args"] = list(command_args)
        context = self._clean_mapping(context)
        lines = [
            "-" * 88,
            f"[{self._now()}] [COMMAND] {component} / {tool_name}",
        ]
        if message:
            lines.append(f"说明: {message}")
        if trace_id:
            lines.append(f"追踪ID: {trace_id}")
        lines.extend(self._format_mapping("上下文", context))
        lines.extend(self._format_mapping("参数", details))
        lines.append("")
        self._append_lines(lines)

    def log_exception(
        self,
        component: str,
        action: str,
        exc: Exception,
        context: dict[str, Any] | None = None,
        trace_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """执行 `log_exception` 对应的业务逻辑，供 `DebugLogger` 使用。"""
        self.log(
            component=component,
            action=action,
            level="ERROR",
            message=str(exc),
            context=context,
            details={"exception_type": type(exc).__name__, **(details or {})},
            trace_id=trace_id,
        )


_debug_logger_singleton: DebugLogger | None = None


def get_debug_logger() -> DebugLogger:
    """获取 `debug_logger` 对应的数据或状态。"""
    global _debug_logger_singleton
    if _debug_logger_singleton is None:
        _debug_logger_singleton = DebugLogger()
    return _debug_logger_singleton


class DebugLoggerProxy:
    """惰性代理，避免模块导入时立刻创建日志目录和文件。"""

    def __getattr__(self, name: str):
        """提供 `__getattr__` 对应的内部辅助逻辑，供 `DebugLoggerProxy` 使用。"""
        return getattr(get_debug_logger(), name)

    def __setattr__(self, name: str, value):
        """提供 `__setattr__` 对应的内部辅助逻辑，供 `DebugLoggerProxy` 使用。"""
        setattr(get_debug_logger(), name, value)


debug_logger = DebugLoggerProxy()
