# Public Network Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every public-Web-initiated network path fail closed against credential disclosure, proxy/DNS bypass, SSRF, cross-session data exposure, and unbounded subprocess output.

**Architecture:** Consume the foundation's host-owned execution profile and add a small set of reusable pinned-transport primitives. Public Web requests use allowlisted DTO projections and session-local logs; every HTTP hop is canonicalized, resolved to public addresses, and connected with the validated DNS result, while Chromium retains its native navigation and cookie behavior through an authenticated loopback CONNECT proxy.

**Tech Stack:** Python 3.10-3.13, FastAPI/Starlette, Playwright, curl_cffi, httpx-compatible response projection, stdlib HMAC/HTTP server/subprocess/queue, pytest.

## Global Constraints

- Complete and push `docs/superpowers/plans/2026-07-27-execution-profile-foundation.md` before Task 1; this plan consumes its host-owned `ExecutionProfile`, factories, required adapter signatures, and payload-escalation rejection without redefining them.
- Public network decisions fail closed: validation, DNS pinning, capability verification, or credential-scope uncertainty aborts the operation.
- Do not add a new runtime dependency; use the existing curl_cffi and standard library.
- Preserve Windows support and Python 3.10-3.13 compatibility.
- Public Web may not read machine cookie files, inherit proxy environment variables, accept caller-selected proxies, or return internal model dictionaries.
- Host canonicalization accepts either no terminal DNS dot or exactly one, rejects multiple terminal dots and every empty label, converts every label to lowercase ASCII IDNA, validates the explicit/default port, rejects userinfo, and rebuilds the request authority before policy checks or transport.
- Redirects are followed manually, validated and DNS-pinned on every hop; maximum redirect count is 5.
- HLS capabilities are task-local, expire after 15 minutes, and authorize only the root URL plus resources discovered in a validated playlist.
- Credentialed CORS uses exact configured origins only; no origin regex and no wildcard response origin.
- Every production change starts with a focused failing test and ends with its focused suite plus the security contract suite.

---

## File Structure

- Consume `shared/execution_profile.py`: use the foundation's sole `ExecutionProfile` definition and session-owned public factory; do not create a second model, factory, or payload parser.
- Create `shared/network/pinned_transport.py`: manual-redirect curl_cffi transport using one isolated curl handle/session per operation and combining `CurlOpt.RESOLVE` with `CurlOpt.PROXY=""`.
- Create `shared/network/browser_connect_proxy.py`: authenticated loopback CONNECT proxy that resolves each requested host, connects to one validated public IP, and relays the opaque TLS tunnel.
- Create `shared/subprocess_env.py`: minimal environment builder for media subprocesses.
- Create `app/web/public_projection.py`: positive allowlist projections for search results, frontend state, events, and logs.
- Modify `app/core/downloaders/hls_proxy.py`: signed task capability and playlist membership store.
- Modify `app/core/downloaders/m3u8.py` and `app/core/downloaders/ffmpeg.py`: pinned curl options, minimal subprocess environment, credential scoping, and bounded stderr.
- Modify `app/core/lib/douyin/link/requester.py`: parsed-host allowlist and pinned per-hop redirect expansion.
- Modify `shared/playwright_network_guard.py`: retain context-level popup/worker/WebSocket policy while Chromium's socket path is pinned by the CONNECT proxy.
- Modify `app/web/server.py`, `app/web/session_runtime.py`, `app/web/ws_session_binding.py`, and `app/web/app_composition.py`: exact CORS and allocation-free WebSocket authentication.
- Modify `app/web/controller.py`, `app/web/ws_bootstrap.py`, `app/services/frontend_state_service.py`, and `app/debug_logger.py`: public DTOs, session-local log views, and URL/signature redaction.

### Task 1: Pinned curl transport and proxy-free subprocess environment

**Files:**
- Create: `shared/network/pinned_transport.py`
- Create: `shared/subprocess_env.py`
- Modify: `app/core/downloaders/hls_proxy.py:71-80`
- Modify: `app/core/downloaders/m3u8.py:676-685,881-991,1690-1792,1847-1853`
- Modify: `app/core/downloaders/ffmpeg.py:289-330`
- Test: `tests/unit/shared/network/test_pinned_transport.py`
- Test: `tests/integration/app/core/downloaders/test_runtime.py`

**Interfaces:**
- Produces: `PinnedResponse(status_code: int, url: str, headers: Mapping[str, str], body: bytes)`.
- Produces: `PinnedTransport.request(method: str, url: str, *, headers: Mapping[str, str], body: bytes | None = None, max_redirects: int = 5) -> PinnedResponse`.
- Produces: `isolated_media_subprocess_env(*, extra: Mapping[str, str] | None = None) -> dict[str, str]`.
- Produces: `CanonicalRequestTarget(url: str, scheme: str, host: str, port: int, authority: str)`, `canonicalize_host(host: str) -> str`, `canonicalize_request_target(url: str) -> CanonicalRequestTarget`, and `curl_resolve_options(target: CanonicalRequestTarget, addresses: Sequence[str], *, disable_proxy: bool = True) -> dict[Any, Any]`.
- Invariant: each `PinnedTransport.request` owns and closes a private curl session/handle; it never mutates a caller-owned or process-shared session.
- Invariant: for every redirect hop, the URL passed to `DomainPolicyEngine`, the `host:port` key in `CurlOpt.RESOLVE`, and the authority in the actual curl request URL come from the same `CanonicalRequestTarget` instance.

- [ ] **Step 1: Write failing transport tests**

```python
def test_public_curl_options_pin_dns_and_disable_environment_proxy():
    target = canonicalize_request_target("https://CDN.Example.:8443/a.ts")
    options = curl_resolve_options(
        target,
        ("8.8.8.8", "2606:4700:4700::1111"),
        disable_proxy=True,
    )
    assert target.url == "https://cdn.example:8443/a.ts"
    assert target.authority == "cdn.example:8443"
    assert options[CurlOpt.RESOLVE] == [
        "cdn.example:8443:8.8.8.8,[2606:4700:4700::1111]"
    ]
    assert options[CurlOpt.PROXY] == ""

@pytest.mark.parametrize("host", [
    "example..com",
    ".example.com",
    "example.com..",
    "example.com" + "." * 3,
    "",
])
def test_canonicalize_host_rejects_empty_labels_and_multiple_terminal_dots(host):
    with pytest.raises(DomainPolicyViolation, match="host"):
        canonicalize_host(host)

def test_canonicalize_host_accepts_exactly_one_terminal_dot_and_idna():
    assert canonicalize_host("BÜCHER.Example.") == "xn--bcher-kva.example"

def test_redirect_hops_use_one_canonical_authority_without_system_dns(monkeypatch, capturing_policy, recording_session_factory):
    system_dns = Mock(side_effect=AssertionError("system DNS fallback"))
    monkeypatch.setattr(socket, "getaddrinfo", system_dns)
    recording_session_factory.responses.extend([
        FakeCurlResponse(
            status_code=302,
            url="https://xn--bcher-kva.example:443/start",
            headers={"Location": "https://CDN.Example.:8443/final"},
            body=b"",
        ),
        FakeCurlResponse(
            status_code=200,
            url="https://cdn.example:8443/final",
            headers={},
            body=b"ok",
        ),
    ])
    transport = PinnedTransport(policy=capturing_policy, session_factory=recording_session_factory)
    result = transport.request("GET", "https://BÜCHER.Example./start", headers={"Host": "attacker.example"})
    assert result.body == b"ok"
    assert capturing_policy.checked_urls == [
        "https://xn--bcher-kva.example:443/start",
        "https://cdn.example:8443/final",
    ]
    assert recording_session_factory.request_urls == capturing_policy.checked_urls
    assert recording_session_factory.resolve_authorities == [
        "xn--bcher-kva.example:443",
        "cdn.example:8443",
    ]
    assert recording_session_factory.request_headers == [{}, {}]
    system_dns.assert_not_called()

def test_pinned_transport_never_mutates_shared_session(shared_session, session_factory):
    transport = PinnedTransport(session_factory=session_factory)
    transport.request("GET", "https://example.com/a", headers={})
    transport.request("GET", "https://example.com/b", headers={})
    assert session_factory.call_count == 2
    assert session_factory.return_values[0] is not session_factory.return_values[1]
    assert shared_session.curl_options == {"sentinel": "unchanged"}
    assert all(session.closed for session in session_factory.return_values)

def test_parallel_pinned_requests_keep_distinct_handles_and_resolve_maps(blocking_session_factory):
    transport = PinnedTransport(session_factory=blocking_session_factory)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(transport.request, "GET", "https://one.example/a", headers={})
        second = executor.submit(transport.request, "GET", "https://two.example/b", headers={})
        blocking_session_factory.both_started.wait(timeout=2.0)
        blocking_session_factory.release.set()
        assert first.result().status_code == 200
        assert second.result().status_code == 200
    sessions = blocking_session_factory.sessions
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert sessions[0].resolve_entries != sessions[1].resolve_entries
    assert all(session.closed for session in sessions)

def test_media_subprocess_environment_drops_proxy_and_cookie_variables(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setenv("COOKIE", "secret")
    env = isolated_media_subprocess_env()
    assert "HTTPS_PROXY" not in env
    assert "COOKIE" not in env
    assert "SystemRoot" in env
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest tests/unit/shared/network/test_pinned_transport.py tests/integration/app/core/downloaders/test_runtime.py -q`

Expected: FAIL because proxy-disabling curl options and `isolated_media_subprocess_env` do not exist and Popen calls do not pass `env`.

- [ ] **Step 3: Create the isolated pinned transport and minimal subprocess environment**

```python
def canonicalize_host(host: str) -> str:
    terminal_dots = len(host) - len(host.rstrip("."))
    if terminal_dots > 1:
        raise DomainPolicyViolation("host has multiple terminal dots")
    source = host[:-1] if terminal_dots == 1 else host
    if not source:
        raise DomainPolicyViolation("invalid host")
    try:
        return ipaddress.ip_address(source).compressed.lower()
    except ValueError:
        labels = source.split(".")
        if any(label == "" for label in labels):
            raise DomainPolicyViolation("host contains an empty label")
        canonical_labels = [label.encode("idna").decode("ascii").lower() for label in labels]
        if any(not label or len(label) > 63 for label in canonical_labels):
            raise DomainPolicyViolation("host contains an invalid IDNA label")
        return ".".join(canonical_labels)

def canonicalize_request_target(url: str) -> CanonicalRequestTarget:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or parts.username is not None or parts.password is not None:
        raise DomainPolicyViolation("invalid public request URL")
    host = canonicalize_host(parts.hostname or "")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise DomainPolicyViolation("invalid public request port") from exc
    authority_host = f"[{host}]" if ":" in host else host
    authority = f"{authority_host}:{port}"
    canonical_url = urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))
    return CanonicalRequestTarget(canonical_url, parts.scheme.lower(), host, port, authority)

def curl_resolve_options(
    target: CanonicalRequestTarget,
    addresses: Sequence[str],
    *,
    disable_proxy: bool = True,
) -> dict[Any, Any]:
    pinned = [f"[{address}]" if ":" in address else address for address in addresses]
    options: dict[Any, Any] = {
        CurlOpt.RESOLVE: [f"{target.host}:{target.port}:{','.join(pinned)}"]
    }
    if disable_proxy:
        options[CurlOpt.PROXY] = ""
    return options

def isolated_media_subprocess_env(*, extra=None) -> dict[str, str]:
    keep = ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATH", "PATHEXT")
    env = {key: os.environ[key] for key in keep if os.environ.get(key)}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env
```

Use the helper in both N_m3u8DL-RE and FFmpeg `Popen` calls. For each high-level operation, `PinnedTransport.request` creates a private curl_cffi session with no inherited proxy, keeps cookies only inside that operation, and closes it in `finally`. At every hop it first creates one `CanonicalRequestTarget`, passes `target.url` to `PUBLIC_DOMAIN_POLICY.resolve_public_addresses`, builds RESOLVE from `target.host` and `target.port`, deletes any caller-supplied `Host`, and calls curl with exactly `target.url`; no later layer reparses the original URL. It sets `allow_redirects=False`, resolves `urljoin(target.url, Location)` into a new target, and strips `Cookie`, `Authorization`, and `Proxy-Authorization` when canonical `(scheme, host, port)` changes. The transport never invokes `socket.getaddrinfo` itself and never submits an uncanonicalized URL to curl, so failure of the injected policy resolver aborts instead of falling back to system DNS.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest tests/unit/shared/network/test_pinned_transport.py tests/integration/app/core/downloaders/test_runtime.py -q`

Expected: PASS, including assertions that each redirect receives its own RESOLVE entry and every protected request has `CurlOpt.PROXY == ""`.

- [ ] **Step 5: Commit**

```bash
git add shared/network/pinned_transport.py shared/subprocess_env.py app/core/downloaders/hls_proxy.py app/core/downloaders/m3u8.py app/core/downloaders/ffmpeg.py tests/unit/shared/network/test_pinned_transport.py tests/integration/app/core/downloaders/test_runtime.py
git commit -m "security: pin public media transports"
```

### Task 2: Task-scoped HLS proxy capabilities and credential scope

**Files:**
- Modify: `app/core/downloaders/hls_proxy.py:126-339`
- Modify: `app/core/downloaders/m3u8.py:744-991`
- Test: `tests/unit/app/core/downloaders/test_hls_proxy_security.py`
- Test: `tests/integration/app/core/downloaders/m3u8/test_lifecycle.py`

**Interfaces:**
- Produces: `HlsCapability(task_id: str, secret: bytes, expires_at: int)`.
- Produces: `_LocalHlsProxy.local_url_for(upstream_url: str) -> str` with query keys `task`, `exp`, `u`, and `sig`.
- Produces: `_LocalHlsProxy.authorize_playlist_resource(parent_url: str, resource_url: str) -> None`.
- Consumes: `PinnedTransport` and `isolated_media_subprocess_env` from Task 1.

- [ ] **Step 1: Write failing capability tests**

```python
def test_hls_proxy_rejects_unsigned_expired_and_unlisted_urls(proxy):
    assert proxy.verify_path("/?u=" + encoded_private_url) is None
    assert proxy.verify_path(proxy.signed_path("https://cdn.example/a.ts", expires_at=1)) is None
    assert proxy.verify_path(proxy.signed_path("https://cdn.example/not-in-playlist.ts")) is None

def test_hls_proxy_strips_credentials_for_cross_origin_playlist_resource(proxy):
    headers = proxy.upstream_headers_for("https://other-cdn.example/a.ts")
    assert "Cookie" not in headers
    assert "Authorization" not in headers
    assert "Proxy-Authorization" not in headers

def test_hls_capability_is_task_local_tamper_evident_and_has_no_wildcard_cors(proxy_a, proxy_b):
    proxy_a.authorize_playlist_resource(
        "https://media.example/master.m3u8",
        "https://cdn.example/segment-1.ts",
    )
    signed_path = proxy_a.path_for("https://cdn.example/segment-1.ts")
    assert proxy_a.verify_path(signed_path) == "https://cdn.example/segment-1.ts"
    assert proxy_b.verify_path(signed_path) is None
    assert proxy_a.verify_path(signed_path.replace("segment-1.ts", "segment-2.ts")) is None
    status, headers, body = proxy_a.handle_path(signed_path)
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") is None
    assert body == b"segment"

def test_hls_membership_contains_only_root_and_parsed_playlist_resources(proxy):
    proxy.record_playlist(
        "https://media.example/master.m3u8",
        "#EXTM3U\n#EXTINF:4,\nsegment-1.ts\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n",
    )
    assert proxy.members == {
        "https://media.example/master.m3u8",
        "https://media.example/segment-1.ts",
        "https://media.example/key.bin",
    }
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest tests/unit/app/core/downloaders/test_hls_proxy_security.py tests/integration/app/core/downloaders/m3u8/test_lifecycle.py -q`

Expected: FAIL because the current `u` parameter is reversible but unsigned and there is no membership/expiry enforcement.

- [ ] **Step 3: Create HMAC verification, expiry, membership, and credential-origin filtering**

```python
def _signature(self, *, task_id: str, expires_at: int, upstream_url: str) -> str:
    payload = f"{task_id}\n{expires_at}\n{upstream_url}".encode("utf-8")
    return hmac.new(self.capability.secret, payload, hashlib.sha256).hexdigest()

def _credential_headers(self, upstream_url: str) -> dict[str, str]:
    headers = dict(self.headers)
    if self._origin(upstream_url) != self._credential_origin:
        headers = {k: v for k, v in headers.items() if k.lower() not in {"cookie", "authorization", "proxy-authorization", "host"}}
    return headers
```

Initialize membership with only the root URL. During playlist rewrite, resolve each URI, require it through the domain policy, add it to the capability membership set, and then generate its signed local URL. Verify task ID, epoch expiry, constant-time signature, normalized URL, and membership before any upstream request. Do not emit any CORS header from `_HlsProxyHandler`.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest tests/unit/app/core/downloaders/test_hls_proxy_security.py tests/integration/app/core/downloaders/m3u8/test_lifecycle.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/downloaders/hls_proxy.py app/core/downloaders/m3u8.py tests/unit/app/core/downloaders/test_hls_proxy_security.py tests/integration/app/core/downloaders/m3u8/test_lifecycle.py
git commit -m "security: sign local HLS capabilities"
```

### Task 3: Douyin host validation and per-hop DNS pinning

**Files:**
- Modify: `app/core/lib/douyin/link/requester.py:1-115`
- Test: `tests/unit/app/core/lib/douyin/link/test_requester.py`

**Interfaces:**
- Produces: `is_douyin_public_host(host: str) -> bool`, matching complete labels for `douyin.com`, `iesdouyin.com`, `tiktok.com`, and `tiktokv.com` only.
- Produces: `is_douyin_public_url(url: str) -> bool`, which rejects userinfo, invalid ports, non-HTTP schemes, and non-platform canonical hosts.
- Consumes: `PinnedTransport.request(method: str, url: str, *, headers: Mapping[str, str], body: bytes | None = None, max_redirects: int = 5) -> PinnedResponse` from Task 1.

- [ ] **Step 1: Write failing host and redirect tests**

```python
@pytest.mark.parametrize("url", [
    "https://attacker.example/?next=https://www.douyin.com/video/1",
    "https://douyin.com.attacker.example/a",
    "https://douyın.com/a",
    "https://user:pass@www.douyin.com/a",
    "https://www.douyin.com:99999/a",
    "https://127.0.0.1/a",
])
async def test_requester_never_fetches_blind_substring_or_private_hosts(url, requester, transport):
    assert await requester.request_url(url) == url
    transport.request.assert_not_called()

@pytest.mark.parametrize("url", [
    "https://WWW.DOUYIN.COM.:443/video/1",
    "https://v.douyin.com./abc",
    "https://www.iesdouyin.com/share/video/1",
])
def test_douyin_host_accepts_only_canonical_platform_authorities(url):
    assert is_douyin_public_url(url)

async def test_requester_validates_and_pins_every_redirect_hop(requester, transport):
    transport.request.return_value = PinnedResponse(200, "https://www.douyin.com/video/1", {}, b"")
    assert await requester.request_url("https://v.douyin.com/abc") == "https://www.douyin.com/video/1"
    transport.request.assert_called_once_with("GET", "https://v.douyin.com/abc", headers=requester.headers, max_redirects=5)
```

- [ ] **Step 2: Run RED test**

Run: `python -m pytest tests/unit/app/core/lib/douyin/link/test_requester.py -q`

Expected: FAIL because the current code checks substrings and delegates redirects/DNS to the caller client.

- [ ] **Step 3: Replace blind substring matching**

Parse the URL once, reject userinfo/non-HTTP schemes/invalid ports, normalize the hostname with `canonicalize_host`, and compare exact suffix labels (`host == suffix or host.endswith("." + suffix)`). The ASCII IDNA result—not the original Unicode spelling or full URL text—is the only value used for the allowlist and resolver. Use `PinnedTransport` for the entire redirect chain. Preserve the existing `content` modes by projecting `PinnedResponse.body`, parsed JSON, headers, final URL, or bytes; do not log response headers containing credentials.

- [ ] **Step 4: Run GREEN test**

Run: `python -m pytest tests/unit/app/core/lib/douyin/link/test_requester.py tests/unit/app/spiders/test_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/lib/douyin/link/requester.py tests/unit/app/core/lib/douyin/link/test_requester.py
git commit -m "security: pin Douyin redirect resolution"
```

### Task 4: Eliminate Playwright DNS TOCTOU

**Files:**
- Create: `shared/network/browser_connect_proxy.py`
- Modify: `shared/playwright_network_guard.py:1-114`
- Modify: `app/core/downloaders/m3u8.py:1248-1355`
- Modify: `app/spiders/douyin/spider.py:36-99`
- Test: `tests/unit/shared/network/test_browser_connect_proxy.py`
- Test: `tests/unit/shared/network/test_playwright_network_guard.py`
- Test: `tests/support/browser_cases/network_guard.py`

**Interfaces:**
- Produces: `BrowserProxyEndpoint(server: str, username: str, password: str)` and `BrowserConnectProxy(policy: DomainPolicyEngine, *, resolver: Callable, connector: Callable, clock: Callable[[], float])`.
- Produces: `BrowserConnectProxy.start() -> BrowserProxyEndpoint`, `BrowserConnectProxy.stop(timeout: float = 3.0) -> None`, and `BrowserConnectProxy.playwright_proxy() -> dict[str, str]`.
- Preserves: `install_public_network_guard(target: Any, policy: DomainPolicyEngine, *, install_http: bool = True, install_websocket: bool = True, install_script: bool = True) -> None` at BrowserContext scope for popup-first-request, HTTP policy, WebSocket, Worker, SharedWorker, and ServiceWorker enforcement.
- Invariant: public browser navigation is HTTPS-only. The proxy implements authenticated CONNECT tunnels only, never terminates TLS, never parses Cookie/Authorization, never reads a cookie file, and never consults an environment/upstream proxy.

- [ ] **Step 1: Write failing CONNECT proxy and context-policy tests**

```python
def test_connect_requires_random_proxy_auth_before_dns(proxy, client, resolver):
    reply = client.exchange(b"CONNECT public.example:443 HTTP/1.1\r\nHost: public.example:443\r\n\r\n")
    assert reply.startswith(b"HTTP/1.1 407")
    resolver.assert_not_called()

def test_authorized_connect_uses_validated_ip_and_canonical_authority(proxy, client, resolver, connector):
    resolver.return_value = ("8.8.8.8", "2606:4700:4700::1111")
    endpoint = proxy.start()
    request = build_connect_request(
        "PUBLIC.Example.:443",
        username=endpoint.username,
        password=endpoint.password,
    )
    reply = client.exchange(request)
    assert reply.startswith(b"HTTP/1.1 200")
    connector.assert_called_once_with(("8.8.8.8", 443), timeout=10.0)
    assert proxy.connection_log == [("public.example", 443, "8.8.8.8")]

def test_connect_rejects_private_resolution_without_opening_socket(proxy, client, resolver, connector):
    resolver.return_value = ("127.0.0.1",)
    endpoint = proxy.start()
    reply = client.exchange(build_connect_request("public.example:443", endpoint.username, endpoint.password))
    assert reply.startswith(b"HTTP/1.1 403")
    connector.assert_not_called()

def test_proxy_ignores_environment_proxy_and_stops_all_tunnels(monkeypatch, proxy, active_tunnel):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    endpoint = proxy.start()
    assert endpoint.server.startswith("http://127.0.0.1:")
    assert "8888" not in endpoint.server
    proxy.register_test_tunnel(active_tunnel)
    proxy.stop(timeout=3.0)
    assert active_tunnel.closed
    assert not proxy.is_running

def test_context_guard_keeps_browser_transport_and_blocks_plain_http(route, request, context):
    request.url = "http://public.example/path"
    install_public_network_guard(context, DomainPolicyEngine())
    context.http_handler(route, request)
    route.abort.assert_called_once_with("blockedbyclient")
    route.fulfill.assert_not_called()
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest tests/unit/shared/network/test_browser_connect_proxy.py tests/unit/shared/network/test_playwright_network_guard.py -q`

Expected: FAIL because no authenticated CONNECT proxy exists and Chromium still resolves destinations itself.

- [ ] **Step 3: Create the authenticated loopback CONNECT transport and wire browser lifecycle**

Bind an ephemeral `127.0.0.1` port and generate 32-byte random username/password values for each browser lifetime. Parse only the CONNECT request line, Host, and Proxy-Authorization; reject all non-CONNECT methods, malformed/IDNA-invalid authorities, non-443 ports, and missing/incorrect credentials before DNS. Canonicalize the host, call `resolve_public_addresses`, connect a raw socket to one returned IP, respond `200 Connection Established`, and relay opaque bytes bidirectionally without TLS termination or payload/header logging. Direct sockets and the minimal proxy thread environment do not read `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, or `NO_PROXY`.

Start the proxy before `browser.launch`/`browser.new_context` and pass `{"server": endpoint.server, "username": endpoint.username, "password": endpoint.password}` through Playwright's proxy option. Install the existing guard on BrowserContext before creating the first Page. Its HTTP handler allows policy-approved HTTPS requests to continue into the CONNECT tunnel, rejects plain HTTP, and keeps the current popup/constructor/WebSocket rules. In a single `finally`, close context/browser first, call `proxy.stop(timeout=3.0)`, reject new CONNECT requests, close active tunnel sockets, join handler threads, and clear secrets. A browser case must set a fake `HTTPS_PROXY`, navigate through the test proxy to an HTTPS fixture, verify fixture cookies survive a redirect, verify popup first navigation is checked, then assert the proxy thread and port are gone after shutdown.

- [ ] **Step 4: Run GREEN tests and browser case**

Run: `python -m pytest tests/unit/shared/network/test_browser_connect_proxy.py tests/unit/shared/network/test_playwright_network_guard.py tests/support/browser_cases/network_guard.py -q`

Expected: PASS; HTTPS uses authenticated CONNECT to the selected public IP, Chromium retains cookies across redirects, unsafe hosts/plain HTTP are blocked, and no proxy thread/tunnel survives shutdown.

- [ ] **Step 5: Commit**

```bash
git add shared/network/browser_connect_proxy.py shared/playwright_network_guard.py app/core/downloaders/m3u8.py app/spiders/douyin/spider.py tests/unit/shared/network/test_browser_connect_proxy.py tests/unit/shared/network/test_playwright_network_guard.py tests/support/browser_cases/network_guard.py
git commit -m "security: pin Playwright through CONNECT proxy"
```

### Task 5: Authenticate WebSocket before context allocation and make CORS exact

**Files:**
- Modify: `app/web/session_runtime.py:200-303`
- Modify: `app/web/ws_session_binding.py:19-72`
- Modify: `app/web/app_composition.py:45-118`
- Modify: `app/web/server.py:72-86`
- Test: `tests/unit/app/web/test_websocket_session_binding.py`
- Test: `tests/contract/web/test_security_hardening.py`

**Interfaces:**
- Produces: `WebSessionRegistry.find(session_id: str) -> WebSessionContext | None`, which never creates a context.
- Changes: WebSocket binding validates access token, exact origin, existing session ID, then its session token; it never calls `get_or_create`.
- Changes: add keyword-only `allowed_origins: Iterable[str] | None = None` to `create_app` and install exact normalized origins only.

- [ ] **Step 1: Write failing allocation and CORS tests**

```python
async def test_invalid_websocket_never_allocates_context(registry, binder, ws):
    ws.headers["origin"] = "https://attacker.example"
    assert await binder.bind(ws) is None
    registry.get_or_create.assert_not_called()

def test_credentialed_cors_rejects_unconfigured_loopback_port(client):
    response = client.options("/api/ping", headers={"Origin": "http://127.0.0.1:65530", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest tests/unit/app/web/test_websocket_session_binding.py tests/contract/web/test_security_hardening.py -q`

Expected: FAIL because origin/session validation currently occurs after `get_or_create`, and CORS accepts every loopback port by regex.

- [ ] **Step 3: Wire registry lookup-only binding and exact CORS configuration**

Normalize the configured origin set once. Remove `allow_origin_regex`; pass only `allow_origins=sorted(exact_origins)` with credentials enabled. In `bind`, check application access and origin first, obtain the session ID, call `registry.find`, reject an absent context, then compare the session token. Preserve the local non-browser no-Origin exception only for loopback clients.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest tests/unit/app/web/test_websocket_session_binding.py tests/contract/web/test_security_hardening.py tests/integration/app/web/test_websocket_server.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web/session_runtime.py app/web/ws_session_binding.py app/web/app_composition.py app/web/server.py tests/unit/app/web/test_websocket_session_binding.py tests/contract/web/test_security_hardening.py tests/integration/app/web/test_websocket_server.py
git commit -m "security: authenticate WebSocket before allocation"
```

### Task 6: Positive public DTOs and session-local redacted logs

**Files:**
- Create: `app/web/public_projection.py`
- Modify: `app/web/search_service.py:101-123`
- Modify: `app/web/controller.py:754-787,1352-1354`
- Modify: `app/web/ws_bootstrap.py:70-100`
- Modify: `app/services/frontend_state_service.py:96-1712`
- Modify: `app/debug_logger.py:169-245`
- Test: `tests/unit/app/web/test_public_projection.py`
- Test: `tests/unit/app/services/test_frontend_state_service.py`
- Test: `tests/unit/app/test_debug_logger.py`
- Test: `tests/contract/web/test_security_hardening.py`

**Interfaces:**
- Produces: `public_search_result(result: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `public_frontend_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]` and `public_video_item(item: VideoItem) -> dict[str, Any]`.
- Changes: add keyword-only `include_file_logs: bool = True` to `FrontendStateService.__init__`; Web constructs it with `include_file_logs=False`, while GUI keeps `True`.

- [ ] **Step 1: Write failing projection and log tests**

```python
def test_public_search_projection_excludes_internal_and_secret_fields():
    projected = public_search_result({
        "status": "success",
        "save_dir": "C:/secret",
        "logs": ["signed?token=x"],
        "items": [{
            "id": "1",
            "title": "ok",
            "url": "https://cdn/x?signature=s",
            "meta": {"cookie": "secret"},
            "actions": [
                "play",
                {"id": "delete", "label": "Delete", "enabled": True, "command": "rm -rf"},
                {"id": "admin_shell", "label": "Shell", "enabled": True},
            ],
            "chunk_progress": {"completed": 2, "total": 4, "percent": 50, "path": "C:/secret"},
        }],
    })
    assert projected == {
        "status": "success",
        "items": [{
            "id": "1",
            "title": "ok",
            "actions": ["play", {"id": "delete", "label": "Delete", "enabled": True}],
            "chunk_progress": {"completed": 2, "total": 4, "percent": 50},
        }],
    }

def test_public_projection_drops_wrong_scalar_types_and_never_calls_coercion():
    class ExplosiveScalar:
        def __init__(self):
            self.str_called = False
            self.int_called = False

        def __str__(self):
            self.str_called = True
            raise AssertionError("__str__ must not run")

        def __int__(self):
            self.int_called = True
            raise AssertionError("__int__ must not run")

    explosive = ExplosiveScalar()
    row = {
        "id": "safe-id",
        "title": {"secret": "cookie=hidden"},
        "status": ["completed", {"token": "hidden"}],
        "progress": explosive,
        "actions": [
            {"id": "delete", "label": explosive, "enabled": True},
            {"id": {"secret": "admin"}, "label": "bad", "enabled": True},
            "play",
        ],
        "chunk_progress": {
            "completed": explosive,
            "total": {"secret": 4},
            "percent": 50,
        },
    }
    assert public_row(row) == {
        "id": "safe-id",
        "actions": ["play"],
        "chunk_progress": {"percent": 50},
    }
    assert not explosive.str_called
    assert not explosive.int_called

class ExplosiveScalarForContractTest:
    def __init__(self):
        self.str_called = False
        self.int_called = False

    def __str__(self):
        self.str_called = True
        raise AssertionError("__str__ must not run")

    def __int__(self):
        self.int_called = True
        raise AssertionError("__int__ must not run")

def test_frontend_endpoint_drops_malicious_scalars_without_500(client, web_controller):
    explosive = ExplosiveScalarForContractTest()
    web_controller.get_frontend_state.return_value = {
        "queue_items": [{"id": "safe-id", "title": explosive, "meta": {"cookie": "secret"}}],
    }
    response = client.get("/api/frontend/state")
    assert response.status_code == 200
    assert response.json()["queue_items"] == [{"id": "safe-id"}]
    assert not explosive.str_called
    assert not explosive.int_called

def test_web_frontend_logs_do_not_merge_global_file_cache(web_service):
    web_service._file_log_cache_store.replace([{"message": "other session secret"}])
    assert all(row["message"] != "other session secret" for row in web_service.log_items())

def test_two_web_sessions_never_share_runtime_logs(web_service_factory):
    first = web_service_factory(owner_id="session-a", include_file_logs=False)
    second = web_service_factory(owner_id="session-b", include_file_logs=False)
    first.record_log("https://user:pass@cdn.example/a?signature=secret", trace_id="trace-a")
    assert len(first.log_items()) == 1
    assert second.log_items() == []
    assert "user:pass" not in first.log_items()[0]["message"]
    assert "secret" not in first.log_items()[0]["message"]
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest tests/unit/app/web/test_public_projection.py tests/unit/app/services/test_frontend_state_service.py tests/unit/app/test_debug_logger.py tests/contract/web/test_security_hardening.py -q`

Expected: FAIL because Web returns raw CLI/VideoItem dictionaries and merges the process-global log file.

- [ ] **Step 3: Define positive projections and Web-local log mode**

```python
PUBLIC_ACTION_IDS = frozenset({"play", "open_directory", "delete", "copy_diagnostics", "cancel", "pause", "resume"})
PUBLIC_ROW_TYPES: dict[str, type | tuple[type, type]] = {
    "id": str,
    "title": str,
    "platform": str,
    "platform_id": str,
    "status": str,
    "progress": (int, type(None)),
    "duration": (str, type(None)),
    "resolution": (str, type(None)),
    "size": (str, type(None)),
    "content_type": (str, type(None)),
    "trace_id": (str, type(None)),
}

def _is_exact_scalar(value: Any, allowed: type | tuple[type, type]) -> bool:
    allowed_types = allowed if isinstance(allowed, tuple) else (allowed,)
    return type(value) in allowed_types

def public_action(value: Any) -> str | dict[str, str | bool] | None:
    if type(value) is str:
        return value if value in PUBLIC_ACTION_IDS else None
    if type(value) is not dict:
        return None
    action_id = value.get("id")
    label = value.get("label")
    enabled = value.get("enabled", True)
    if type(action_id) is not str or action_id not in PUBLIC_ACTION_IDS:
        return None
    if label is not None and type(label) is not str:
        return None
    if type(enabled) is not bool:
        return None
    projected: dict[str, str | bool] = {"id": action_id, "enabled": enabled}
    if label is not None:
        projected["label"] = label
    return projected

def public_chunk_progress(value: Any) -> dict[str, int | None] | None:
    if type(value) is not dict:
        return None
    projected: dict[str, int | None] = {}
    for key in ("completed", "total", "percent"):
        if key not in value:
            continue
        field_value = value[key]
        if field_value is None or type(field_value) is int:
            projected[key] = field_value
    return projected or None

def public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if type(row) is not dict:
        return {}
    projected = {}
    for key, allowed in PUBLIC_ROW_TYPES.items():
        if key in row and _is_exact_scalar(row[key], allowed):
            projected[key] = row[key]
    raw_actions = row.get("actions")
    action_values = raw_actions if type(raw_actions) in {list, tuple} else ()
    actions = [projected_action for value in action_values if (projected_action := public_action(value)) is not None]
    if actions:
        projected["actions"] = actions
    chunk_progress = public_chunk_progress(row.get("chunk_progress"))
    if chunk_progress is not None:
        projected["chunk_progress"] = chunk_progress
    return projected
```

Create equally explicit projectors for `events` (`time`, redacted `message`), `solutions` (`title`, `description`, `icon_file`), and log rows (`id`, `time`, `level`, `source`, `trace_id`, redacted `message_summary`, redacted `message`). Every projector accepts only exact built-in `str`, `int`, `bool`, or `None` types declared for that field; `bool` is not accepted as `int`, subclasses/custom scalar objects are not accepted, and no projector calls `str`, `int`, `bool`, serialization hooks, or formatting on rejected values. Nested containers are accepted only at named schema positions and only as exact built-in `dict`, `list`, or `tuple`; unknown keys and wrong-typed fields are discarded. If a required identifier is absent, drop that row and record the stable internal error code `PUBLIC_DTO_REQUIRED_FIELD_INVALID` without including the rejected value. Never redact a raw dictionary and then return the remainder. Search returns only public status/count/items/error fields. Web snapshots/events pass through the public projection before HTTP or WebSocket serialization. When `include_file_logs=False`, `FrontendStateService.log_items` reads only its `AppState` buffer. Extend debug redaction to replace URL userinfo and the values of `token`, `signature`, `expires`, and `auth_key` before both file and UI logging; omit source URLs, absolute paths, proxy values, Authorization/Cookie values, and nested `meta` from public DTOs.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest tests/unit/app/web/test_public_projection.py tests/unit/app/services/test_frontend_state_service.py tests/unit/app/test_debug_logger.py tests/contract/web/test_security_hardening.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/web/public_projection.py app/web/search_service.py app/web/controller.py app/web/ws_bootstrap.py app/services/frontend_state_service.py app/debug_logger.py tests/unit/app/web/test_public_projection.py tests/unit/app/services/test_frontend_state_service.py tests/unit/app/test_debug_logger.py tests/contract/web/test_security_hardening.py
git commit -m "security: project session-safe Web payloads"
```

### Task 7: Bound FFmpeg stderr and run the security gate

**Files:**
- Modify: `app/core/downloaders/ffmpeg.py:287-431`
- Test: `tests/integration/app/core/downloaders/test_runtime.py`
- Test: `tests/performance/test_runtime_budgets.py`

**Interfaces:**
- Changes: FFmpeg uses `queue.Queue[bytes | None](maxsize=256)`; the pump performs non-blocking replacement/coalescing while preserving one EOF sentinel and the existing 12-line diagnostic tail.

- [ ] **Step 1: Write the failing bounded-pressure test**

```python
def test_ffmpeg_stderr_pump_is_bounded_and_still_delivers_eof(monkeypatch, tmp_path):
    process = FastNoisyFakeProcess(lines=10_000)
    observed = run_ffmpeg_with_slow_consumer(process, tmp_path)
    assert observed.max_queue_size <= 256
    assert observed.finished
    assert observed.stderr_tail[-1] == "line-9999"
```

- [ ] **Step 2: Run RED test**

Run: `python -m pytest tests/integration/app/core/downloaders/test_runtime.py -k "stderr and bounded" -q`

Expected: FAIL because the queue is currently unbounded.

- [ ] **Step 3: Replace the unbounded queue with bounded newest-progress admission**

Use `queue.Queue(maxsize=256)`. On `queue.Full`, discard the oldest progress line and enqueue the newest line; for EOF, keep removing one item until the sentinel is accepted. Never block the stderr pump and retain the `deque(maxlen=12)` failure tail.

- [ ] **Step 4: Run focused and complete security verification**

Run: `python -m pytest tests/integration/app/core/downloaders/test_runtime.py tests/performance/test_runtime_budgets.py -q`

Expected: PASS.

Run: `python -m pytest tests/unit/shared/network tests/unit/app/core/downloaders/test_hls_proxy_security.py tests/unit/app/core/lib/douyin/link/test_requester.py tests/unit/app/web tests/contract/web/test_security_hardening.py tests/integration/app/web/test_websocket_server.py -q`

Expected: PASS.

Run: `python -m ruff check shared app tests/unit/shared/network tests/unit/app/core/downloaders/test_hls_proxy_security.py tests/unit/app/core/lib/douyin/link/test_requester.py tests/unit/app/web tests/contract/web/test_security_hardening.py`

Expected: PASS with no diagnostics.

- [ ] **Step 5: Commit and push the public-boundary batch**

```bash
git add app/core/downloaders/ffmpeg.py tests/integration/app/core/downloaders/test_runtime.py tests/performance/test_runtime_budgets.py
git commit -m "perf: bound FFmpeg stderr buffering"
git push origin main
```
