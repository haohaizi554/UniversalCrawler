"""Read-only network, proxy, and external-tool diagnostics."""

from __future__ import annotations

import importlib.util
import inspect
import math
import queue
import re
import socket
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from app.config import cfg
from app.core.downloaders.external import (
    ExternalToolRunner,
    FFmpegExternalTool,
    NM3U8DLREExternalTool,
)
from app.core.plugins.run_options import normalize_proxy_url
from app.core.tools.contracts import ToolContext, ToolManifest, ToolRunResult
from shared.network_proxy import requests_proxy_mapping


_DEFAULT_HOST = "example.com"
_DEFAULT_TIMEOUT_SECONDS = 2.0
_MIN_TIMEOUT_SECONDS = 0.1
_MAX_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.02

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "host": {
            "type": "string",
            "title": "DNS 主机",
            "description": "要解析的主机名；留空时使用网络地址中的主机",
            "default": _DEFAULT_HOST,
        },
        "url": {
            "type": "string",
            "title": "网络地址",
            "description": "用于连通性检查的 HTTP 或 HTTPS 地址",
            "default": f"https://{_DEFAULT_HOST}/",
        },
        "proxy": {
            "type": "string",
            "title": "代理",
            "description": "代理预设或自定义代理；留空时读取项目的 MissAV 代理配置",
            "default": "",
        },
        "timeout_seconds": {
            "type": "number",
            "title": "探测超时（秒）",
            "minimum": _MIN_TIMEOUT_SECONDS,
            "maximum": _MAX_TIMEOUT_SECONDS,
            "default": _DEFAULT_TIMEOUT_SECONDS,
        },
    },
    "additionalProperties": False,
}


def _construct_contract(contract_type: type, values: Mapping[str, Any]):
    """Construct shared contracts while accepting their compatibility aliases."""
    try:
        parameters = inspect.signature(contract_type).parameters.values()
    except (TypeError, ValueError):
        return contract_type(**dict(values))

    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for parameter in parameters:
        if parameter.name in {"self", "args", "kwargs"}:
            continue
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            continue
        if parameter.name in values:
            kwargs[parameter.name] = values[parameter.name]
        elif parameter.default is parameter.empty:
            missing.append(parameter.name)
    if missing:
        names = ", ".join(missing)
        raise TypeError(
            f"Unsupported {contract_type.__name__} contract fields: {names}"
        )
    return contract_type(**kwargs)


def _build_manifest() -> ToolManifest:
    title = "网络与外部工具诊断"
    summary = "检查 DNS、代理、网络连通性以及下载所需外部工具"
    return _construct_contract(
        ToolManifest,
        {
            "id": "environment_diagnostics",
            "tool_id": "environment_diagnostics",
            "name": title,
            "title": title,
            "description": summary,
            "summary": summary,
            "category": "diagnostics",
            "version": "1.0",
            "input_schema": _INPUT_SCHEMA,
            "parameters": _INPUT_SCHEMA,
            "schema": _INPUT_SCHEMA,
            "safety_level": "read_only",
            "read_only": True,
            "destructive": False,
            "execution_mode": "worker",
            "run_in_worker": True,
            "background": True,
            "supports_cancel": True,
            "cancellable": True,
            "requires": (),
            "icon": "stethoscope",
            "sort_order": 70,
        },
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
    failed = status != "success"
    return _construct_contract(
        ToolRunResult,
        {
            "status": status,
            "success": not failed,
            "ok": not failed,
            "cancelled": status == "cancelled",
            "message": message,
            "data": payload,
            "output": payload,
            "details": payload,
            "result": payload,
            "payload": payload,
            "error_code": error_code,
            "code": error_code,
            "error": message if failed else "",
            "errors": (message,) if failed else (),
        },
    )


def _context_inputs(context: ToolContext) -> Mapping[str, Any]:
    for name in (
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


def _is_cancelled(context: ToolContext) -> bool:
    for name in (
        "cancel_event",
        "cancellation_event",
        "stop_event",
        "cancellation_token",
    ):
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


def _configured_proxy() -> str:
    try:
        return str(cfg.get("missav", "proxy_url", "") or "").strip()
    except (AttributeError, TypeError, ValueError):
        return ""


def _input_proxy(inputs: Mapping[str, Any]) -> str:
    if "proxy" in inputs:
        return str(inputs.get("proxy") or "").strip()
    return _configured_proxy()


def _input_timeout(inputs: Mapping[str, Any]) -> float:
    value = inputs.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(timeout):
        return _DEFAULT_TIMEOUT_SECONDS
    return max(_MIN_TIMEOUT_SECONDS, min(timeout, _MAX_TIMEOUT_SECONDS))


def _input_url(inputs: Mapping[str, Any], host: str) -> str:
    value = str(inputs.get("url") or "").strip()
    if value:
        return value
    host_for_url = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"https://{host_for_url}/"


def _input_host(inputs: Mapping[str, Any]) -> str:
    value = str(inputs.get("host") or "").strip()
    if value:
        return value.strip("[]")
    url = str(inputs.get("url") or "").strip()
    if url:
        try:
            return str(urlsplit(url).hostname or _DEFAULT_HOST)
        except ValueError:
            return _DEFAULT_HOST
    return _DEFAULT_HOST


def _valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    if any(character.isspace() for character in host) or any(
        mark in host for mark in ("/", "\\", "@")
    ):
        return False
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        pass
    try:
        ascii_host = host.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_host.split(".")
    return bool(labels) and all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and re.fullmatch(r"[A-Za-z0-9-]+", label)
        for label in labels
    )


def _url_error(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "网络地址必须是有效的 HTTP 或 HTTPS 地址"
        if parsed.username is not None or parsed.password is not None:
            return "网络地址不能包含用户名或密码"
        parsed.port
    except ValueError:
        return "网络地址必须是有效的 HTTP 或 HTTPS 地址"
    return ""


def _proxy_error(raw_proxy: str) -> str:
    if not raw_proxy:
        return ""
    lowered = raw_proxy.casefold()
    if lowered in {
        "direct",
        "none",
        "no proxy",
        "system",
        "system proxy",
        "直连",
        "系统代理",
    }:
        return ""
    scheme_match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", raw_proxy)
    if scheme_match and scheme_match.group(1).lower() not in {
        "http",
        "https",
        "socks4",
        "socks5",
    }:
        return "代理仅支持 HTTP、HTTPS、SOCKS4 或 SOCKS5"
    normalized = normalize_proxy_url(raw_proxy)
    if not normalized:
        return "代理配置无效"
    try:
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https", "socks4", "socks5"}:
            return "代理仅支持 HTTP、HTTPS、SOCKS4 或 SOCKS5"
        if not parsed.hostname or parsed.port is None:
            return "代理配置必须包含有效的主机和端口"
    except ValueError:
        return "代理配置必须包含有效的主机和端口"
    return ""


def _proxy_mode(raw_proxy: str) -> str:
    lowered = raw_proxy.casefold().strip()
    if lowered in {"system", "system proxy", "系统代理"}:
        return "system"
    if not lowered or lowered in {"direct", "none", "no proxy", "直连"}:
        return "direct"
    return "explicit"


def _redacted_endpoint(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if not host:
            return "<redacted>"
        host_text = f"[{host}]" if ":" in host else host
        try:
            port = parsed.port
        except ValueError:
            port = None
        port_text = f":{port}" if port is not None else ""
        return f"{parsed.scheme.lower()}://{host_text}{port_text}"
    except (TypeError, ValueError):
        return "<redacted>"


_CREDENTIAL_URL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s]+)@")
_SECRET_VALUE_RE = re.compile(
    r"(?i)((?:[?&]|\b)(?:access[_-]?token|api[_-]?key|authorization|cookie|password|passwd|proxy[_-]?authorization|secret|token)\s*[=:]\s*)[^&\s]+"
)


def _safe_error(exc: BaseException) -> str:
    text = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    text = _CREDENTIAL_URL_RE.sub(r"\1***@", text)
    text = _SECRET_VALUE_RE.sub(r"\1***", text)
    try:
        home = str(Path.home())
        if home:
            text = text.replace(home, "<home>")
    except (OSError, RuntimeError):
        pass
    return text[:300]


def _check(status: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "details": details,
    }


def _proxy_check(raw_proxy: str, normalized_proxy: str) -> dict[str, Any]:
    configured_mode = _proxy_mode(raw_proxy)
    effective_mode = "explicit" if normalized_proxy else "direct"
    if configured_mode == "system" and not normalized_proxy:
        message = "系统代理按项目网络规范以显式直连方式检查"
    elif normalized_proxy:
        message = "显式代理配置有效"
    else:
        message = "当前使用显式直连"
    return _check(
        "ok",
        message,
        configured=bool(raw_proxy),
        configured_mode=configured_mode,
        effective_mode=effective_mode,
        endpoint=_redacted_endpoint(normalized_proxy),
        environment_inherited=False,
    )


def _dns_check(host: str, port: int) -> dict[str, Any]:
    records = _socket_getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for record in records:
        try:
            address = str(record[4][0])
        except (IndexError, TypeError):
            continue
        if address and address not in addresses:
            addresses.append(address)
        if len(addresses) >= 8:
            break
    if not addresses:
        return _check("error", "DNS 未返回可用地址", host=host, addresses=[])
    return _check("ok", "DNS 解析成功", host=host, addresses=addresses)


def _http_check(url: str, proxy: str, timeout: float) -> dict[str, Any]:
    mapping = requests_proxy_mapping(proxy)
    explicit_mapping = {
        scheme: value for scheme in ("http", "https") if (value := mapping.get(scheme))
    }
    opener = _build_url_opener(ProxyHandler(explicit_mapping))
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "Range": "bytes=0-0",
            "User-Agent": "UniversalCrawlerPro-Diagnostics/1.0",
        },
        method="GET",
    )
    target = _redacted_endpoint(url)
    try:
        with opener.open(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            response.read(1)
            final_url = _redacted_endpoint(
                str(getattr(response, "geturl", lambda: url)())
            )
    except HTTPError as exc:
        return _check(
            "warning",
            f"网络目标已响应 HTTP {exc.code}",
            target=target,
            status_code=int(exc.code),
            reachable=True,
        )
    except (OSError, URLError) as exc:
        return _check(
            "error",
            "网络连接失败",
            target=target,
            error_type=type(exc).__name__,
            detail=_safe_error(exc),
        )
    status = "ok" if status_code < 400 else "warning"
    return _check(
        status,
        f"网络目标已响应 HTTP {status_code}",
        target=target,
        final_target=final_url,
        status_code=status_code,
        reachable=True,
    )


def _executable_name(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name


def _external_tool_check(
    display_name: str, resolver: Callable[[], str | None]
) -> dict[str, Any]:
    executable = resolver()
    if not executable:
        return _check(
            "unavailable",
            f"未找到 {display_name}",
            available=False,
            executable="",
        )
    return _check(
        "ok",
        f"{display_name} 可用",
        available=True,
        executable=_executable_name(executable),
    )


def _playwright_check() -> dict[str, Any]:
    payload = _probe_playwright_runtime()
    package_available = bool(payload.get("package_available"))
    browser_available = bool(payload.get("browser_available"))
    details: dict[str, Any] = {
        "package_available": package_available,
        "browser_available": browser_available,
        "executable": _executable_name(str(payload.get("executable") or "")),
    }
    if payload.get("detail"):
        details["detail"] = _safe_error(RuntimeError(str(payload["detail"])))
    if browser_available:
        return _check("ok", "Playwright Chromium 可用", **details)
    if package_available:
        return _check(
            "unavailable", "Playwright 已安装，但 Chromium 运行时不可用", **details
        )
    return _check("unavailable", "未安装 Playwright", **details)


_PROBE_LABELS = {
    "dns": "DNS",
    "http": "网络连接",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "n_m3u8dl_re": "N_m3u8DL-RE",
    "playwright": "Playwright",
}


def _failed_probe(name: str, exc: BaseException) -> dict[str, Any]:
    return _check(
        "error",
        f"{_PROBE_LABELS[name]} 探测失败",
        error_type=type(exc).__name__,
        detail=_safe_error(exc),
    )


def _timed_out_probe(name: str, timeout: float) -> dict[str, Any]:
    return _check(
        "timeout",
        f"{_PROBE_LABELS[name]} 探测超时",
        timeout_seconds=timeout,
    )


def _run_parallel_probes(
    context: ToolContext,
    operations: Mapping[str, Callable[[], dict[str, Any]]],
    timeout: float,
) -> tuple[bool, dict[str, dict[str, Any]]]:
    result_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

    def execute(name: str, operation: Callable[[], dict[str, Any]]) -> None:
        try:
            result = operation()
        except Exception as exc:
            # Probe failures become sanitized findings instead of escaping the run.
            result = _failed_probe(name, exc)
        result_queue.put((name, result))

    for name, operation in operations.items():
        threading.Thread(
            target=execute,
            args=(name, operation),
            name=f"environment-diagnostics-{name}",
            daemon=True,
        ).start()

    pending = set(operations)
    results: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout
    while pending:
        if _is_cancelled(context):
            return True, results
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            name, result = result_queue.get(
                timeout=min(_POLL_INTERVAL_SECONDS, remaining)
            )
        except queue.Empty:
            continue
        if name in pending:
            pending.remove(name)
            results[name] = result

    while pending:
        try:
            name, result = result_queue.get_nowait()
        except queue.Empty:
            break
        if name in pending:
            pending.remove(name)
            results[name] = result
    for name in pending:
        results[name] = _timed_out_probe(name, timeout)
    return _is_cancelled(context), results


def _probe_playwright_runtime() -> dict[str, Any]:
    try:
        if importlib.util.find_spec("playwright.sync_api") is None:
            return {
                "package_available": False,
                "browser_available": False,
                "executable": "",
            }
    except (ImportError, ModuleNotFoundError, ValueError):
        return {
            "package_available": False,
            "browser_available": False,
            "executable": "",
        }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = str(playwright.chromium.executable_path or "")
            browser_available = bool(executable and Path(executable).is_file())
        return {
            "package_available": True,
            "browser_available": browser_available,
            "executable": executable,
        }
    except Exception as exc:
        return {
            "package_available": True,
            "browser_available": False,
            "executable": "",
            "detail": _safe_error(exc),
        }


_socket_getaddrinfo = socket.getaddrinfo
_build_url_opener = build_opener
_resolve_ffmpeg = FFmpegExternalTool.resolve_executable
_resolve_nm3u8 = NM3U8DLREExternalTool.resolve_executable


def _resolve_ffprobe() -> str | None:
    return ExternalToolRunner.resolve_executable(
        "ffprobe.exe",
        "ffprobe",
        ["-version"],
    )


class EnvironmentDiagnosticsTool:
    """Diagnose the runtime environment without changing it."""

    manifest = _build_manifest()

    def validate(self, context: ToolContext) -> list[str]:
        inputs = _context_inputs(context)
        errors: list[str] = []
        host = _input_host(inputs)
        if not _valid_host(host):
            errors.append("DNS 主机名无效")

        target_url = _input_url(inputs, host)
        if error := _url_error(target_url):
            errors.append(error)

        raw_proxy = _input_proxy(inputs)
        if error := _proxy_error(raw_proxy):
            errors.append(error)

        value = inputs.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            timeout = math.nan
        if (
            isinstance(value, bool)
            or not math.isfinite(timeout)
            or not (_MIN_TIMEOUT_SECONDS <= timeout <= _MAX_TIMEOUT_SECONDS)
        ):
            errors.append(
                f"探测超时必须在 {_MIN_TIMEOUT_SECONDS:g} 到 {_MAX_TIMEOUT_SECONDS:g} 秒之间"
            )
        return errors

    def run(self, context: ToolContext) -> ToolRunResult:
        if _is_cancelled(context):
            return self._cancelled_result()

        errors = self.validate(context)
        if errors:
            return _build_result(
                "error",
                errors[0],
                data={"status": "invalid", "checks": {}, "errors": errors},
                error_code="invalid_input",
            )
        if _is_cancelled(context):
            return self._cancelled_result()

        inputs = _context_inputs(context)
        host = _input_host(inputs)
        target_url = _input_url(inputs, host)
        timeout = _input_timeout(inputs)
        raw_proxy = _input_proxy(inputs)
        normalized_proxy = normalize_proxy_url(raw_proxy)
        parsed_url = urlsplit(target_url)
        port = parsed_url.port or (443 if parsed_url.scheme.lower() == "https" else 80)

        operations: dict[str, Callable[[], dict[str, Any]]] = {
            "dns": lambda: _dns_check(host, port),
            "http": lambda: _http_check(target_url, normalized_proxy, timeout),
            "ffmpeg": lambda: _external_tool_check("ffmpeg", _resolve_ffmpeg),
            "ffprobe": lambda: _external_tool_check("ffprobe", _resolve_ffprobe),
            "n_m3u8dl_re": lambda: _external_tool_check("N_m3u8DL-RE", _resolve_nm3u8),
            "playwright": _playwright_check,
        }
        cancelled, probe_results = _run_parallel_probes(context, operations, timeout)
        if cancelled:
            return self._cancelled_result()

        checks: dict[str, dict[str, Any]] = {
            "dns": probe_results["dns"],
            "proxy": _proxy_check(raw_proxy, normalized_proxy),
            "http": probe_results["http"],
            "ffmpeg": probe_results["ffmpeg"],
            "ffprobe": probe_results["ffprobe"],
            "n_m3u8dl_re": probe_results["n_m3u8dl_re"],
            "playwright": probe_results["playwright"],
        }
        counts = {
            "ok": sum(check["status"] == "ok" for check in checks.values()),
            "warning": sum(check["status"] == "warning" for check in checks.values()),
            "unavailable": sum(
                check["status"] == "unavailable" for check in checks.values()
            ),
            "error": sum(
                check["status"] in {"error", "timeout"} for check in checks.values()
            ),
        }
        health_status = "healthy" if counts["ok"] == len(checks) else "degraded"
        message = (
            "诊断完成：网络与外部工具均可用"
            if health_status == "healthy"
            else "诊断完成：发现环境问题"
        )
        return _build_result(
            "success",
            message,
            data={
                "status": health_status,
                "checks": checks,
                "summary": counts,
            },
        )

    @staticmethod
    def _cancelled_result() -> ToolRunResult:
        return _build_result(
            "cancelled",
            "网络与外部工具诊断已取消",
            data={"status": "cancelled", "checks": {}},
            error_code="cancelled",
        )


TOOL = EnvironmentDiagnosticsTool()
tool = TOOL
manifest = TOOL.manifest


def validate(context: ToolContext) -> list[str]:
    return TOOL.validate(context)


def run(context: ToolContext) -> ToolRunResult:
    return TOOL.run(context)


__all__ = [
    "EnvironmentDiagnosticsTool",
    "TOOL",
    "manifest",
    "run",
    "tool",
    "validate",
]
