"""为所有 Python 网络客户端提供经过 TLS 校验的 DNS 故障回退。

正常情况下始终使用操作系统 DNS。仅当系统解析失败时，才通过固定到服务商
公网地址的 DNS-over-HTTPS 查询 A/AAAA 记录；这样即使本机 DNS 服务器返回
SERVFAIL，HTTPS 证书、SNI 和原始 URL 主机名仍保持不变。
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

GetAddrInfo = Callable[..., list[tuple[Any, ...]]]
DoHLookup = Callable[[str, int], tuple[tuple[str, ...], float]]

_LOGGER = logging.getLogger(__name__)
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_INSTALL_LOCK = threading.Lock()
_INSTALL_ATTRIBUTE = "_ucrawl_resilient_dns_getaddrinfo"
_MAX_DOH_RESPONSE_BYTES = 128 * 1024
_MIN_CACHE_TTL_SECONDS = 30.0
_MAX_CACHE_TTL_SECONDS = 300.0
_SYSTEM_CACHE_TTL_SECONDS = 30.0
_SYSTEM_FAILURE_BACKOFF_SECONDS = 60.0


@dataclass(frozen=True)
class _DoHProvider:
    host: str
    bootstrap_ips: tuple[str, ...]
    path: str


# bootstrap IP 只负责建立到 DoH 服务商的首个 TLS 连接；证书仍按 host 校验。
# 阿里公共 DNS 在中国大陆优先，Cloudflare 作为跨网络环境的第二回退。
_DOH_PROVIDERS = (
    _DoHProvider("dns.alidns.com", ("223.5.5.5", "223.6.6.6"), "/resolve"),
    _DoHProvider("cloudflare-dns.com", ("1.1.1.1", "1.0.0.1"), "/dns-query"),
)

_CHROMIUM_DOH_SERVERS = (
    ("https://dns.alidns.com/dns-query{?dns}", ("223.5.5.5", "223.6.6.6")),
    ("https://cloudflare-dns.com/dns-query{?dns}", ("1.1.1.1", "1.0.0.1")),
)

_NON_PUBLIC_DNS_SUFFIXES = (
    ".example",
    ".home.arpa",
    ".internal",
    ".invalid",
    ".lan",
    ".local",
    ".localhost",
    ".onion",
    ".test",
)


@dataclass(frozen=True)
class _CacheEntry:
    addresses: tuple[str, ...]
    expires_at: float


def _normalize_host(host: object) -> str:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return ""
    text = str(host or "").strip().rstrip(".")
    if not text:
        return ""
    try:
        return text.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""


def _is_doh_candidate(host: str) -> bool:
    if not host or "." not in host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    return not any(host == suffix[1:] or host.endswith(suffix) for suffix in _NON_PUBLIC_DNS_SUFFIXES)


def _address_matches_family(address: str, family: int) -> bool:
    try:
        version = ipaddress.ip_address(address).version
    except ValueError:
        return False
    if family == socket.AF_INET:
        return version == 4
    if family == socket.AF_INET6:
        return version == 6
    return True


def _query_doh_provider(
    provider: _DoHProvider,
    bootstrap_ip: str,
    host: str,
    record_type: int,
    *,
    timeout: float = 4.0,
) -> tuple[tuple[str, ...], float]:
    """使用固定连接地址访问 DoH，同时保留服务商主机名的 TLS 校验。"""
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(
        provider.host,
        443,
        timeout=timeout,
        context=context,
    )

    def create_pinned_connection(
        _address,
        connect_timeout=None,
        source_address=None,
    ):
        effective_timeout = timeout if connect_timeout is None else connect_timeout
        return _ORIGINAL_CREATE_CONNECTION(
            (bootstrap_ip, 443),
            effective_timeout,
            source_address,
        )

    # HTTPSConnection 仍以 provider.host 作为 SNI/证书主机名，只替换 TCP 目的地址。
    connection._create_connection = create_pinned_connection  # type: ignore[attr-defined]
    query = urlencode({"name": host, "type": record_type})
    try:
        connection.request(
            "GET",
            f"{provider.path}?{query}",
            headers={
                "Accept": "application/dns-json",
                "User-Agent": "UniversalCrawlerPro-DNS/1",
            },
        )
        response = connection.getresponse()
        payload = response.read(_MAX_DOH_RESPONSE_BYTES + 1)
        if response.status != 200 or len(payload) > _MAX_DOH_RESPONSE_BYTES:
            return (), 0.0
        decoded = json.loads(payload.decode("utf-8"))
    finally:
        connection.close()

    if not isinstance(decoded, dict) or int(decoded.get("Status", -1)) != 0:
        return (), 0.0
    answers = decoded.get("Answer")
    if not isinstance(answers, list):
        return (), 0.0

    addresses: list[str] = []
    ttls: list[float] = []
    expected_version = 4 if record_type == 1 else 6
    for answer in answers:
        if not isinstance(answer, dict) or int(answer.get("type", 0) or 0) != record_type:
            continue
        raw_address = str(answer.get("data") or "").strip()
        try:
            parsed_address = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        if parsed_address.version != expected_version:
            continue
        normalized = str(parsed_address)
        if normalized not in addresses:
            addresses.append(normalized)
        try:
            ttls.append(float(answer.get("TTL", _MIN_CACHE_TTL_SECONDS)))
        except (TypeError, ValueError):
            ttls.append(_MIN_CACHE_TTL_SECONDS)

    if not addresses:
        return (), 0.0
    ttl = min(ttls or [_MIN_CACHE_TTL_SECONDS])
    return tuple(addresses), max(_MIN_CACHE_TTL_SECONDS, min(ttl, _MAX_CACHE_TTL_SECONDS))


def resolve_via_doh(host: str, family: int) -> tuple[tuple[str, ...], float]:
    """依次查询受信 DoH 服务；全部失败时返回空结果并保留原系统 DNS 异常。"""
    record_types = (28,) if family == socket.AF_INET6 else (1,)
    if family not in {socket.AF_INET, socket.AF_INET6}:
        # 大多数媒体 CDN 同时提供 IPv4；先用单次 A 查询缩短故障恢复时间。
        record_types = (1, 28)

    for record_type in record_types:
        for provider in _DOH_PROVIDERS:
            for bootstrap_ip in provider.bootstrap_ips:
                try:
                    addresses, ttl = _query_doh_provider(
                        provider,
                        bootstrap_ip,
                        host,
                        record_type,
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                if addresses:
                    return addresses, ttl
    return (), 0.0


def chromium_resilient_dns_args() -> tuple[str, str]:
    """生成 Chromium 增强引导 DoH 参数，使浏览器不依赖已故障的系统 DNS。"""
    configuration = {
        "servers": [
            {
                "template": template,
                "endpoints": [{"ips": list(bootstrap_ips)}],
            }
            for template, bootstrap_ips in _CHROMIUM_DOH_SERVERS
        ]
    }
    serialized = json.dumps(configuration, ensure_ascii=True, separators=(",", ":"))
    return (
        "--dns-over-https-mode=automatic",
        f"--dns-over-https-templates={serialized}",
    )


class ResilientDNSResolver:
    """先走系统 DNS，失败后用 DoH，并让校验层与传输层复用短期缓存。"""

    def __init__(
        self,
        *,
        system_resolver: GetAddrInfo | None = None,
        doh_lookup: DoHLookup | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._system_resolver = system_resolver or socket.getaddrinfo
        self._doh_lookup = doh_lookup or resolve_via_doh
        self._clock = clock or time.monotonic
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = threading.RLock()
        self._system_health_lock = threading.Lock()
        self._system_unhealthy_until = 0.0

    def _cached_addresses(self, host: str, family: int) -> tuple[str, ...]:
        with self._cache_lock:
            entry = self._cache.get(host)
            if entry is None:
                return ()
            if entry.expires_at <= self._clock():
                self._cache.pop(host, None)
                return ()
            return tuple(address for address in entry.addresses if _address_matches_family(address, family))

    def _cache_addresses(self, host: str, addresses: tuple[str, ...], ttl: float) -> None:
        normalized = tuple(dict.fromkeys(address for address in addresses if _address_matches_family(address, 0)))
        if not normalized:
            return
        bounded_ttl = max(_MIN_CACHE_TTL_SECONDS, min(float(ttl), _MAX_CACHE_TTL_SECONDS))
        with self._cache_lock:
            self._cache[host] = _CacheEntry(normalized, self._clock() + bounded_ttl)

    def _system_dns_in_backoff(self) -> bool:
        with self._system_health_lock:
            return self._system_unhealthy_until > self._clock()

    def _mark_system_dns_failure(self) -> None:
        with self._system_health_lock:
            self._system_unhealthy_until = max(
                self._system_unhealthy_until,
                self._clock() + _SYSTEM_FAILURE_BACKOFF_SECONDS,
            )

    def _mark_system_dns_success(self) -> None:
        with self._system_health_lock:
            self._system_unhealthy_until = 0.0

    def _resolve_doh_addresses(self, host: str, family: int) -> tuple[tuple[str, ...], float]:
        lookup_family = family if family in {socket.AF_INET, socket.AF_INET6} else socket.AF_UNSPEC
        addresses, ttl = self._doh_lookup(host, lookup_family)
        return (
            tuple(address for address in addresses if _address_matches_family(address, lookup_family)),
            ttl,
        )

    @staticmethod
    def _addresses_from_infos(addr_infos: list[tuple[Any, ...]]) -> tuple[str, ...]:
        addresses: list[str] = []
        for addr_info in addr_infos:
            try:
                address = str(addr_info[4][0])
                ipaddress.ip_address(address)
            except (IndexError, TypeError, ValueError):
                continue
            if address not in addresses:
                addresses.append(address)
        return tuple(addresses)

    def _materialize_addr_infos(
        self,
        addresses: tuple[str, ...],
        port,
        family: int,
        socket_type: int,
        protocol: int,
        flags: int,
    ) -> list[tuple[Any, ...]]:
        results: list[tuple[Any, ...]] = []
        numeric_host_flag = int(getattr(socket, "AI_NUMERICHOST", 0))
        for address in addresses:
            address_family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
            if family not in {socket.AF_UNSPEC, 0, address_family}:
                continue
            infos = self._system_resolver(
                address,
                port,
                address_family,
                socket_type,
                protocol,
                flags | numeric_host_flag,
            )
            results.extend(infos)
        if not results:
            raise socket.gaierror(socket.EAI_NONAME, "DNS fallback returned no usable address")
        return results

    def __call__(
        self,
        host,
        port,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        normalized_host = _normalize_host(host)
        if not normalized_host:
            return self._system_resolver(host, port, family, type, proto, flags)

        cached = self._cached_addresses(normalized_host, family)
        if cached:
            return self._materialize_addr_infos(cached, port, family, type, proto, flags)

        doh_candidate = _is_doh_candidate(normalized_host)
        if doh_candidate and self._system_dns_in_backoff():
            addresses, ttl = self._resolve_doh_addresses(normalized_host, family)
            if addresses:
                self._cache_addresses(normalized_host, addresses, ttl)
                _LOGGER.warning("系统 DNS 仍不可用，已对 %s 直接使用安全 DNS", normalized_host)
                return self._materialize_addr_infos(addresses, port, family, type, proto, flags)

        try:
            addr_infos = self._system_resolver(host, port, family, type, proto, flags)
        except OSError as system_error:
            if not doh_candidate:
                raise
            addresses, ttl = self._resolve_doh_addresses(normalized_host, family)
            if not addresses:
                raise system_error
            self._cache_addresses(normalized_host, addresses, ttl)
            self._mark_system_dns_failure()
            _LOGGER.warning("系统 DNS 解析失败，已对 %s 启用安全 DNS 回退", normalized_host)
            return self._materialize_addr_infos(addresses, port, family, type, proto, flags)

        self._mark_system_dns_success()
        addresses = self._addresses_from_infos(addr_infos)
        if addresses and doh_candidate:
            self._cache_addresses(normalized_host, addresses, _SYSTEM_CACHE_TTL_SECONDS)
        return addr_infos


def install_resilient_dns(
    *,
    socket_module=socket,
    doh_lookup: DoHLookup | None = None,
) -> GetAddrInfo:
    """幂等替换 ``getaddrinfo``，让 requests/httpx 等入口共享同一回退。"""
    with _INSTALL_LOCK:
        installed = getattr(socket_module, _INSTALL_ATTRIBUTE, None)
        if callable(installed):
            return installed

        resolver = ResilientDNSResolver(
            system_resolver=socket_module.getaddrinfo,
            doh_lookup=doh_lookup,
        )

        def resilient_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return resolver(host, port, family, type, proto, flags)

        resilient_getaddrinfo._ucrawl_dns_resolver = resolver  # type: ignore[attr-defined]
        socket_module.getaddrinfo = resilient_getaddrinfo
        setattr(socket_module, _INSTALL_ATTRIBUTE, resilient_getaddrinfo)
        return resilient_getaddrinfo


__all__ = [
    "ResilientDNSResolver",
    "chromium_resilient_dns_args",
    "install_resilient_dns",
    "resolve_via_doh",
]
