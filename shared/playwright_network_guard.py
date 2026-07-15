"""跨运行时层共享、按失败关闭原则执行的 Playwright 网络守卫。"""

from __future__ import annotations

from typing import Any
import urllib.parse

from shared.runtime_options import DomainPolicyEngine, DomainPolicyViolation


_BLOCK_SCRIPT_NETWORK_CONSTRUCTORS = r"""
(() => {
  const marker = Symbol.for("ucrawl.publicNetworkGuard");
  if (globalThis[marker]) return;
  Object.defineProperty(globalThis, marker, { value: true });
  for (const name of ["WebSocket", "Worker", "SharedWorker"]) {
    if (typeof globalThis[name] !== "function") continue;
    const BlockedNetworkConstructor = function () {
      throw new DOMException(
        `${name} is disabled by the public network policy`,
        "SecurityError"
      );
    };
    if (name === "WebSocket") {
      Object.defineProperties(BlockedNetworkConstructor, {
        CONNECTING: { value: 0 },
        OPEN: { value: 1 },
        CLOSING: { value: 2 },
        CLOSED: { value: 3 },
      });
    }
    Object.defineProperty(globalThis, name, {
      value: BlockedNetworkConstructor,
      configurable: false,
      writable: false,
    });
  }
})();
"""


def _mark_installed(owner: Any, marker: str) -> None:
    try:
        setattr(owner, marker, True)
    except (AttributeError, TypeError):
        # 即使未来 Playwright 包装器仅支持 __slots__，重复安装守卫仍然安全。
        pass


def install_public_network_guard(
    target: Any,
    policy: DomainPolicyEngine,
    *,
    install_http: bool = True,
    install_websocket: bool = True,
    install_script: bool = True,
) -> None:
    """保护 Page 或 BrowserContext 创建的每个请求。

    调用方应优先传入 ``BrowserContext``，以覆盖弹窗的首次导航；旧版
    Playwright 实现或测试替身仍可传入 Page。
    """

    add_init_script = getattr(target, "add_init_script", None)
    if install_script and callable(add_init_script) and not bool(
        getattr(target, "_ucrawl_public_script_guard_installed", False)
    ):
        try:
            add_init_script(_BLOCK_SCRIPT_NETWORK_CONSTRUCTORS)
        except Exception as exc:
            raise DomainPolicyViolation("浏览器无法安装脚本网络隔离策略") from exc
        _mark_installed(target, "_ucrawl_public_script_guard_installed")

    register_route = getattr(target, "route", None)
    if install_http and callable(register_route) and not bool(
        getattr(target, "_ucrawl_public_http_route_installed", False)
    ):

        def guard_route(route: Any, request: Any) -> None:
            request_url = str(getattr(request, "url", "") or "")
            scheme = urllib.parse.urlsplit(request_url).scheme.lower()
            if scheme in {"about", "blob", "data"}:
                route.continue_()
                return
            try:
                policy.require_public_url(request_url)
            except DomainPolicyViolation:
                route.abort("blockedbyclient")
                return
            route.continue_()

        register_route("**/*", guard_route)
        _mark_installed(target, "_ucrawl_public_http_route_installed")

    register_websocket_route = getattr(target, "route_web_socket", None)
    if install_websocket and callable(register_websocket_route) and not bool(
        getattr(target, "_ucrawl_public_websocket_route_installed", False)
    ):

        def guard_websocket(websocket_route: Any) -> None:
            request_url = str(getattr(websocket_route, "url", "") or "")
            parts = urllib.parse.urlsplit(request_url)
            if parts.scheme.lower() in {"ws", "wss"}:
                http_scheme = "https" if parts.scheme.lower() == "wss" else "http"
                request_url = urllib.parse.urlunsplit(parts._replace(scheme=http_scheme))
            try:
                policy.require_public_url(request_url)
            except DomainPolicyViolation:
                websocket_route.close(code=1008, reason="Blocked by public network policy")
                return
            websocket_route.connect_to_server()

        register_websocket_route("**/*", guard_websocket)
        _mark_installed(target, "_ucrawl_public_websocket_route_installed")
