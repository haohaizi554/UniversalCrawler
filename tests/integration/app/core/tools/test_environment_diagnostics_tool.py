from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


# The shared contracts are supplied by a parallel task. This fallback keeps the
# focused test independently runnable until that task lands in the worktree.
try:
    from app.core.tools.contracts import ToolManifest, ToolRunResult
except ModuleNotFoundError as exc:
    if exc.name != "app.core.tools.contracts":
        raise

    contracts = types.ModuleType("app.core.tools.contracts")

    @dataclass(frozen=True, slots=True)
    class ToolManifest:
        id: str
        title: str
        summary: str
        input_schema: dict[str, Any]
        safety_level: str
        execution_mode: str
        supports_cancel: bool = False

    @dataclass(frozen=True, slots=True)
    class ToolContext:
        inputs: dict[str, Any] = field(default_factory=dict)
        cancel_event: threading.Event = field(default_factory=threading.Event)

    @dataclass(frozen=True, slots=True)
    class ToolRunResult:
        status: str
        message: str = ""
        data: dict[str, Any] = field(default_factory=dict)
        error_code: str = ""

        @property
        def success(self) -> bool:
            return self.status == "success"

        @property
        def cancelled(self) -> bool:
            return self.status == "cancelled"

    contracts.ToolManifest = ToolManifest
    contracts.ToolContext = ToolContext
    contracts.ToolRunResult = ToolRunResult
    sys.modules[contracts.__name__] = contracts

from app.core.tools.builtin import environment_diagnostics as diagnostics


def _context(
    inputs: dict[str, Any] | None = None,
    *,
    cancel_event: threading.Event | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        inputs=dict(inputs or {}),
        cancel_event=cancel_event or threading.Event(),
    )


def _status(result: ToolRunResult) -> str:
    status = getattr(result, "status", None)
    if status:
        return str(status)
    if bool(getattr(result, "cancelled", False)):
        return "cancelled"
    return "success" if bool(getattr(result, "success", False)) else "error"


def _data(result: ToolRunResult) -> dict[str, Any]:
    for name in ("data", "output", "details", "result"):
        value = getattr(result, name, None)
        if isinstance(value, dict):
            return value
    return {}


def _error_code(result: ToolRunResult) -> str:
    for name in ("error_code", "code"):
        value = getattr(result, name, "")
        if value:
            return str(value)
    return str(_data(result).get("error_code") or "")


class _Response:
    status = 204

    def __init__(self, url: str) -> None:
        self._url = url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int = -1) -> bytes:
        return b""


def _install_available_tool_probes(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "_resolve_ffmpeg", lambda: r"C:\tools\ffmpeg.exe")
    monkeypatch.setattr(
        diagnostics, "_resolve_ffprobe", lambda: r"C:\tools\ffprobe.exe"
    )
    monkeypatch.setattr(
        diagnostics, "_resolve_nm3u8", lambda: r"C:\tools\N_m3u8DL-RE.exe"
    )
    monkeypatch.setattr(
        diagnostics,
        "_probe_playwright_runtime",
        lambda: {
            "package_available": True,
            "browser_available": True,
            "executable": r"C:\browser\chrome.exe",
        },
    )


def _install_immediate_network(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics,
        "_socket_getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("203.0.113.10", 443))],
    )

    class _Opener:
        def open(self, request, timeout: float) -> _Response:
            return _Response(request.full_url)

    monkeypatch.setattr(diagnostics, "_build_url_opener", lambda *_handlers: _Opener())


def test_manifest_declares_read_only_cancellable_background_diagnostics() -> None:
    assert isinstance(diagnostics.manifest, ToolManifest)
    assert getattr(
        diagnostics.manifest, "id", getattr(diagnostics.manifest, "tool_id", "")
    ) == ("environment_diagnostics")
    assert getattr(diagnostics.manifest, "safety_level", "") == "read_only" or bool(
        getattr(diagnostics.manifest, "read_only", False)
    )
    assert getattr(diagnostics.manifest, "execution_mode", "") in {
        "background",
        "worker",
    } or bool(getattr(diagnostics.manifest, "run_in_worker", False))
    assert bool(getattr(diagnostics.manifest, "supports_cancel", True))
    timeout_schema = diagnostics.manifest.input_schema["properties"]["timeout_seconds"]
    assert timeout_schema["maximum"] <= 5


def test_validate_rejects_unsafe_network_inputs_without_echoing_secrets() -> None:
    errors = diagnostics.validate(
        _context(
            {
                "host": "bad host/path",
                "url": "ftp://alice:url-secret@example.com/archive",
                "proxy": "ftp://alice:proxy-secret@127.0.0.1:21",
                "timeout_seconds": 30,
            }
        )
    )

    joined = " ".join(str(error) for error in errors)
    assert errors
    assert "DNS" in joined
    assert "HTTP" in joined
    assert "代理" in joined
    assert "超时" in joined
    assert "url-secret" not in joined
    assert "proxy-secret" not in joined


def test_validate_accepts_project_proxy_presets_and_short_timeout() -> None:
    errors = diagnostics.validate(
        _context(
            {
                "host": "example.com",
                "url": "https://example.com/health",
                "proxy": "Clash (7890)",
                "timeout_seconds": 0.5,
            }
        )
    )

    assert errors == []


def test_run_reports_network_and_external_tools_with_redacted_output(
    monkeypatch,
) -> None:
    _install_available_tool_probes(monkeypatch)
    seen_timeouts: list[float] = []
    expected_proxy = "http://alice:proxy-secret@127.0.0.1:7890"

    def getaddrinfo(host: str, port: int, **_kwargs: Any):
        assert (host, port) == ("example.com", 443)
        return [
            (2, 1, 6, "", ("203.0.113.10", 443)),
            (2, 1, 6, "", ("203.0.113.10", 443)),
            (23, 1, 6, "", ("2001:db8::10", 443, 0, 0)),
        ]

    class _Opener:
        def open(self, request, timeout: float) -> _Response:
            seen_timeouts.append(timeout)
            return _Response(request.full_url)

    def build_opener(*handlers: object) -> _Opener:
        proxy_mappings = [getattr(handler, "proxies", None) for handler in handlers]
        assert {"http": expected_proxy, "https": expected_proxy} in proxy_mappings
        return _Opener()

    monkeypatch.setattr(diagnostics, "_socket_getaddrinfo", getaddrinfo)
    monkeypatch.setattr(diagnostics, "_build_url_opener", build_opener)

    result = diagnostics.run(
        _context(
            {
                "host": "example.com",
                "url": "https://example.com/health?token=url-secret",
                "proxy": expected_proxy,
                "timeout_seconds": 0.5,
            }
        )
    )

    assert _status(result) == "success"
    data = _data(result)
    assert data["status"] == "healthy"
    assert set(data["checks"]) == {
        "dns",
        "proxy",
        "http",
        "ffmpeg",
        "ffprobe",
        "n_m3u8dl_re",
        "playwright",
    }
    assert all(check["status"] == "ok" for check in data["checks"].values())
    assert data["checks"]["dns"]["details"]["addresses"] == [
        "203.0.113.10",
        "2001:db8::10",
    ]
    assert data["checks"]["proxy"]["details"]["endpoint"] == "http://127.0.0.1:7890"
    assert data["checks"]["ffmpeg"]["details"]["executable"] == "ffmpeg.exe"
    assert seen_timeouts and max(seen_timeouts) <= 0.5
    rendered = repr(result)
    assert "proxy-secret" not in rendered
    assert "url-secret" not in rendered
    assert "alice" not in rendered


def test_run_treats_missing_optional_tools_as_a_degraded_diagnosis(monkeypatch) -> None:
    _install_immediate_network(monkeypatch)
    monkeypatch.setattr(diagnostics, "_resolve_ffmpeg", lambda: None)
    monkeypatch.setattr(diagnostics, "_resolve_ffprobe", lambda: None)
    monkeypatch.setattr(diagnostics, "_resolve_nm3u8", lambda: None)
    monkeypatch.setattr(
        diagnostics,
        "_probe_playwright_runtime",
        lambda: {
            "package_available": True,
            "browser_available": False,
            "executable": "",
        },
    )

    result = diagnostics.run(
        _context(
            {
                "host": "example.com",
                "url": "https://example.com/",
                "proxy": "直连",
                "timeout_seconds": 0.5,
            }
        )
    )

    assert _status(result) == "success"
    checks = _data(result)["checks"]
    assert _data(result)["status"] == "degraded"
    assert checks["proxy"]["status"] == "ok"
    assert checks["ffmpeg"]["status"] == "unavailable"
    assert checks["ffprobe"]["status"] == "unavailable"
    assert checks["n_m3u8dl_re"]["status"] == "unavailable"
    assert checks["playwright"]["status"] == "unavailable"


def test_run_honors_cancellation_before_starting_any_probe(monkeypatch) -> None:
    cancel_event = threading.Event()
    cancel_event.set()

    def unexpected_probe(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("cancelled diagnostics must not start external work")

    monkeypatch.setattr(diagnostics, "_socket_getaddrinfo", unexpected_probe)
    monkeypatch.setattr(diagnostics, "_resolve_ffmpeg", unexpected_probe)

    result = diagnostics.run(_context(cancel_event=cancel_event))

    assert _status(result) == "cancelled"
    assert _error_code(result) == "cancelled"


def test_run_returns_promptly_when_cancelled_during_dns(monkeypatch) -> None:
    _install_available_tool_probes(monkeypatch)
    _install_immediate_network(monkeypatch)
    cancel_event = threading.Event()

    def blocking_dns(*_args: Any, **_kwargs: Any):
        cancel_event.set()
        time.sleep(1)
        return []

    monkeypatch.setattr(diagnostics, "_socket_getaddrinfo", blocking_dns)
    started = time.monotonic()

    result = diagnostics.run(
        _context(
            {"host": "example.com", "timeout_seconds": 1},
            cancel_event=cancel_event,
        )
    )

    assert time.monotonic() - started < 0.5
    assert _status(result) == "cancelled"
    assert _error_code(result) == "cancelled"


def test_run_applies_one_short_deadline_to_parallel_probes(monkeypatch) -> None:
    _install_available_tool_probes(monkeypatch)
    _install_immediate_network(monkeypatch)

    def blocking_dns(*_args: Any, **_kwargs: Any):
        time.sleep(1)
        return []

    monkeypatch.setattr(diagnostics, "_socket_getaddrinfo", blocking_dns)
    started = time.monotonic()

    result = diagnostics.run(
        _context(
            {
                "host": "example.com",
                "url": "https://example.com/",
                "proxy": "直连",
                "timeout_seconds": 0.1,
            }
        )
    )

    assert time.monotonic() - started < 0.5
    assert _status(result) == "success"
    assert _data(result)["status"] == "degraded"
    assert _data(result)["checks"]["dns"]["status"] == "timeout"


def test_repeated_timeouts_keep_probe_threads_and_pending_work_bounded() -> None:
    script = r'''
import json
import threading
import time
from types import SimpleNamespace

from app.core.tools.builtin import environment_diagnostics as diagnostics

blocked = threading.Event()
started = []
started_lock = threading.Lock()


def block_forever(*_args, **_kwargs):
    with started_lock:
        started.append(threading.get_ident())
    blocked.wait()
    raise AssertionError("the permanent probe must never resume")


diagnostics._dns_check = block_forever
diagnostics._http_check = block_forever
diagnostics._external_tool_check = block_forever
diagnostics._playwright_check = block_forever

context = SimpleNamespace(
    inputs={
        "host": "example.com",
        "url": "https://example.com/",
        "proxy": "direct",
        "timeout_seconds": 0.1,
    },
    cancel_event=threading.Event(),
)

caller_errors = []


def invoke_diagnostics():
    try:
        diagnostics.run(context)
    except BaseException as exc:
        caller_errors.append(type(exc).__name__)


callers = [threading.Thread(target=invoke_diagnostics) for _ in range(8)]
for caller in callers:
    caller.start()
for caller in callers:
    caller.join(timeout=2)

started_at = time.monotonic()
result = diagnostics.run(context)
elapsed = time.monotonic() - started_at

checks = result.data["checks"]
probe_names = ("dns", "http", "ffmpeg", "ffprobe", "n_m3u8dl_re", "playwright")
print(json.dumps({
    "elapsed": elapsed,
    "caller_errors": caller_errors,
    "callers_alive": sum(caller.is_alive() for caller in callers),
    "started": len(started),
    "threads": len([
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("environment-diagnostics-")
    ]),
    "reasons": [checks[name]["details"].get("reason") for name in probe_names],
}))
'''

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["caller_errors"] == []
    assert payload["callers_alive"] == 0
    assert payload["started"] == 6
    assert payload["threads"] == 6
    assert payload["elapsed"] < 0.4
    assert payload["reasons"] == ["probe_capacity_exhausted"] * 6
