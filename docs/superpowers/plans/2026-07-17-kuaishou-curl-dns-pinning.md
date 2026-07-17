# Kuaishou curl DNS Pinning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every Kuaishou short-link curl request to the public DNS addresses validated for that exact hop, while failing closed when pinning cannot be guaranteed.

**Architecture:** Keep the change inside `KuaishouShareRuntimeMixin`: a small formatter converts validated IP addresses into request-scoped `CurlOpt.RESOLVE`, and the existing bounded policy worker prepares those curl kwargs under the shared 15-second deadline. Manual redirects continue one hop at a time; every next hop is validated and pinned exactly once, while unsupported proxy DNS enters the existing browser fallback.

**Tech Stack:** Python 3.10+, pytest, `curl_cffi`, `DomainPolicyEngine`, `unittest.mock`.

## Global Constraints

- Change only the Kuaishou short-link transport, its focused unit tests, and active design documentation.
- Preserve the 15-second total deadline, 5-redirect maximum, 2 MiB body cap, platform host allowlist, response cleanup, and browser fallback semantics.
- Support default HTTP/HTTPS ports, custom ports, IPv4, IPv6, and IDNA hostnames; reject explicit ports outside 1 through 65535.
- Addresses must come from `DomainPolicyEngine.resolve_public_addresses()` and reach that same hop through request-scoped `CurlOpt.RESOLVE`.
- Empty or invalid addresses, policy timeout, malformed URL, or proxy-side DNS must fail closed before `curl_get` runs.
- Do not change Cookie persistence, Playwright waits, navigation, reload behavior, global DNS policy, m3u8/HLS code, test taxonomy, file-size budgets, or unrelated dirty files.
- Keep tests in `tests/unit/app/spiders/kuaishou/test_share_resolution.py` without a business marker or whitelist; preserve the configured 75 percent branch-coverage gate.

---

## File Structure

- Modify `app/spiders/kuaishou/share_runtime.py`: format DNS pins, prepare bounded per-hop curl kwargs, reject unsupported proxies, and pass the pin into curl.
- Modify `tests/unit/app/spiders/kuaishou/test_share_resolution.py`: deterministic public DNS fixture, RED pin/fail-closed/redirect/browser-flow contracts, and updated bounded-worker tests.
- Modify `docs/superpowers/specs/2026-07-17-kuaishou-curl-dns-pinning-design.md`: record the proxy and explicit-port boundaries found during security review.

### Task 1: Establish failing transport contracts

**Files:**
- Modify: `tests/unit/app/spiders/kuaishou/test_share_resolution.py:1-259`

**Interfaces:**
- Consumes: `KuaishouSpider._resolve_short_share_url(url: str) -> str`, `KuaishouSpider.run() -> None`, and `DomainPolicyEngine.resolve_public_addresses(url: str) -> tuple[str, ...]`.
- Produces: executable contracts for request-scoped `curl_options`, redirect re-pinning, fail-closed proxy/port/address handling, and HTTP-success browser bypass.

- [ ] **Step 1: Replace implicit network access with a deterministic public policy fixture**

Add the imports and use a real `DomainPolicyEngine` backed by known global addresses:

```python
from curl_cffi.const import CurlOpt
from shared.runtime_options import DomainPolicyEngine


def _public_policy(*addresses: str) -> DomainPolicyEngine:
    resolved = addresses or ("93.184.216.34",)
    return DomainPolicyEngine(
        resolver=lambda *_args, **_kwargs: [
            (None, None, None, None, (address, 443))
            for address in resolved
        ]
    )


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.config = {"timeout": 60}
    spider.user_agent = "test-agent"
    spider.log = Mock()
    spider._effective_proxy_server = Mock(return_value=None)
    spider._public_domain_policy = _public_policy()
    return spider
```

- [ ] **Step 2: Add RED pin-format and fail-closed tests**

```python
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_pins_validated_public_addresses(request_get: Mock) -> None:
    spider = _spider()
    spider._public_domain_policy = _public_policy(
        "2001:4860:4860::8888",
        "93.184.216.34",
    )
    url = "https://www.kuaishou.com:8443/f/example"
    response = Mock(url="https://www.kuaishou.com:8443/profile/example", status_code=200, headers={})
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "www.kuaishou.com:8443:[2001:4860:4860::8888],93.184.216.34"
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.kuaishou.com/f/example", "www.kuaishou.com:443:93.184.216.34"),
        ("http://www.kuaishou.com/f/example", "www.kuaishou.com:80:93.184.216.34"),
    ],
)
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_uses_scheme_default_port(
    request_get: Mock,
    url: str,
    expected: str,
) -> None:
    spider = _spider()
    response = Mock(url=url.replace("/f/", "/profile/"), status_code=200, headers={})
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [expected]


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_preserves_idna_and_trailing_dot_host(request_get: Mock) -> None:
    spider = _spider()
    url = "https://快手.kuaishou.com./f/example"
    response = Mock(url="https://快手.kuaishou.com./profile/example", status_code=200, headers={})
    request_get.return_value = response

    spider._resolve_short_share_url(url)

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "xn--66tu6c.kuaishou.com.:443:93.184.216.34"
    ]


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_when_no_address_is_resolved(request_get: Mock) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = ()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "93.184.216.34,127.0.0.1"])
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_for_invalid_pinned_address(
    request_get: Mock,
    address: str,
) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = (address,)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_for_zero_port(request_get: Mock) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.return_value = ("93.184.216.34",)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    url = "https://www.kuaishou.com:0/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()
```

- [ ] **Step 3: Add RED redirect, proxy, and run-branch tests**

```python
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_redirect_revalidates_and_repins_each_hop(request_get: Mock) -> None:
    spider = _spider()
    policy = Mock(spec=DomainPolicyEngine)
    policy.REDIRECT_STATUS_CODES = DomainPolicyEngine.REDIRECT_STATUS_CODES
    policy.resolve_public_addresses.side_effect = [
        ("93.184.216.34",),
        ("2001:4860:4860::8888",),
    ]
    spider._public_domain_policy_engine = Mock(return_value=policy)
    first_url = "https://v.kuaishou.com/example"
    final_url = "https://www.kuaishou.com:8443/short-video/3xj8abcde"
    first = Mock(url=first_url, status_code=302, headers={"Location": final_url})
    final = Mock(url=final_url, status_code=200, headers={}, encoding="utf-8")
    request_get.side_effect = [first, final]

    assert spider._resolve_short_share_url(first_url) == final_url
    assert request_get.call_args_list[0].kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "v.kuaishou.com:443:93.184.216.34"
    ]
    assert request_get.call_args_list[1].kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "www.kuaishou.com:8443:[2001:4860:4860::8888]"
    ]
    assert policy.resolve_public_addresses.call_count == 2
    first.close.assert_called_once()
    spider._close_pending_share_response()
    final.close.assert_called_once()


@pytest.mark.parametrize(
    "proxy",
    ["http://127.0.0.1:7890", "socks5h://127.0.0.1:7890"],
)
@patch("app.spiders.kuaishou.share_runtime.curl_get")
def test_short_link_transport_fails_closed_when_proxy_controls_dns(
    request_get: Mock,
    proxy: str,
) -> None:
    spider = _spider()
    spider._effective_proxy_server.return_value = proxy
    url = "https://www.kuaishou.com/f/example"

    assert spider._resolve_short_share_url(url) == url
    request_get.assert_not_called()


def test_short_link_http_success_reuses_detail_without_browser_fallback() -> None:
    spider = _spider()
    spider.keyword = "https://www.kuaishou.com/f/example"
    spider.task_builder = Mock()
    spider.task_builder.build_download_meta.return_value = {"trace_id": "share-test"}
    spider.new_trace_id = Mock(return_value="share-test")
    spider.debug_state = Mock()
    spider.emit_video = Mock()
    spider._emit_finished = Mock()
    final_url = "https://www.kuaishou.com/short-video/3xj8abcde"
    html = (
        '<script>window.__APOLLO_STATE__='
        '{"defaultClient":{"VisionVideoDetailPhoto:3xj8abcde":'
        '{"caption":"分享作品","photoUrl":"https://cdn.example.com/video.mp4"}}};'
        "</script>"
    )
    response = Mock(url=final_url, status_code=200, headers={}, encoding="utf-8")

    def perform_request(_url, **kwargs):
        payload = html.encode("utf-8")
        assert kwargs["content_callback"](payload) == len(payload)
        return response

    with patch("app.spiders.kuaishou.share_runtime.curl_get", side_effect=perform_request) as request_get, patch(
        "app.spiders.kuaishou.spider.sync_playwright"
    ) as sync_playwright:
        spider.run()

    assert request_get.call_args.kwargs["curl_options"][CurlOpt.RESOLVE] == [
        "www.kuaishou.com:443:93.184.216.34"
    ]
    sync_playwright.assert_not_called()
    spider.emit_video.assert_called_once()
    response.close.assert_called_once()
```

- [ ] **Step 4: Move deadline tests to the actual DNS boundary**

Replace both timeout tests with the actual DNS boundary:

```python
def test_short_link_policy_validation_obeys_total_deadline() -> None:
    spider = _spider()
    blocker = threading.Event()
    policy = Mock(spec=DomainPolicyEngine)
    policy.resolve_public_addresses.side_effect = lambda *_args, **_kwargs: blocker.wait(0.5)
    spider._public_domain_policy_engine = Mock(return_value=policy)
    started = time.perf_counter()

    with pytest.raises(CurlRequestsError, match="validation timeout"):
        spider._restricted_short_link_request_kwargs(
            "https://v.kuaishou.com/example",
            deadline=time.monotonic() + 0.02,
        )

    assert time.perf_counter() - started < 0.25


def test_short_link_policy_validation_bounds_hung_workers() -> None:
    spider = _spider()
    blocker = threading.Event()
    entered = threading.Event()
    policy = Mock(spec=DomainPolicyEngine)

    def block_validation(*_args, **_kwargs):
        entered.set()
        blocker.wait(0.5)
        return ("93.184.216.34",)

    policy.resolve_public_addresses.side_effect = block_validation
    spider._public_domain_policy_engine = Mock(return_value=policy)
    gate = threading.BoundedSemaphore(1)
    try:
        with patch("app.spiders.kuaishou.share_runtime._SHORT_LINK_POLICY_SLOTS", gate):
            with pytest.raises(CurlRequestsError, match="validation timeout"):
                spider._restricted_short_link_request_kwargs(
                    "https://v.kuaishou.com/first",
                    deadline=time.monotonic() + 0.02,
                )
            assert entered.is_set()
            with pytest.raises(CurlRequestsError, match="validation timeout"):
                spider._restricted_short_link_request_kwargs(
                    "https://v.kuaishou.com/second",
                    deadline=time.monotonic() + 0.02,
                )
    finally:
        blocker.set()

    assert policy.resolve_public_addresses.call_count == 1
```

- [ ] **Step 5: Run the focused module and verify RED**

Run: `python -m pytest tests/unit/app/spiders/kuaishou/test_share_resolution.py -q`

Expected: the new tests fail because `curl_get` has no `curl_options`, the policy resolver is not consumed, and proxy-side DNS still reaches transport. Existing tests remain collected without import or fixture errors.

#### Phase 2: Implement bounded per-hop DNS pinning and return Task 1 to GREEN

**Files:**
- Modify: `app/spiders/kuaishou/share_runtime.py:1-258`
- Modify: `docs/superpowers/specs/2026-07-17-kuaishou-curl-dns-pinning-design.md`

**Interfaces:**
- Consumes: `DomainPolicyEngine.resolve_public_addresses(url: str) -> tuple[str, ...]` and the existing semaphore/deadline.
- Produces: `_short_link_curl_resolve_options(url: str, addresses: tuple[str, ...]) -> dict[object, list[str]]` and `_restricted_short_link_request_kwargs(...) -> {"curl_options": ...}`.

- [ ] **Step 1: Add the strict curl pin formatter**

Add `ipaddress` and `CurlOpt` imports, then add this helper before the mixin:

```python
def _short_link_curl_resolve_options(
    url: str,
    addresses: tuple[str, ...],
) -> dict[object, list[str]]:
    """Pin curl to the exact public addresses validated for one short-link hop."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
        if parts.scheme.lower() not in {"http", "https"}:
            raise ValueError("unsupported URL scheme")
        host = str(parts.hostname or "").encode("idna").decode("ascii")
        if not host:
            raise ValueError("missing URL host")
        port = parts.port
        if port is None:
            port = 443 if parts.scheme.lower() == "https" else 80
        if not 1 <= port <= 65535:
            raise ValueError("invalid URL port")

        pinned: list[str] = []
        for raw_address in addresses:
            address = ipaddress.ip_address(str(raw_address or "").strip())
            if not address.is_global:
                raise ValueError("non-public pinned address")
            rendered = f"[{address}]" if address.version == 6 else str(address)
            if rendered not in pinned:
                pinned.append(rendered)
        if not pinned:
            raise ValueError("no public address to pin")
    except (UnicodeError, ValueError) as exc:
        raise DomainPolicyViolation("无法固定快手短链的公网 DNS 结果") from exc
    return {CurlOpt.RESOLVE: [f"{host}:{port}:{','.join(pinned)}"]}
```

- [ ] **Step 2: Return request-scoped curl kwargs from the bounded worker**

Replace the worker's `validate()` body with:

```python
def validate() -> None:
    try:
        if not self._url_matches_hosts(
            url,
            ("kuaishou.com", "chenzhongtech.com"),
        ):
            raise DomainPolicyViolation("url 主机不属于目标平台")
        addresses = self._public_domain_policy_engine().resolve_public_addresses(url)
        result["value"] = {
            "curl_options": _short_link_curl_resolve_options(url, addresses)
        }
    except Exception as exc:
        result["error"] = exc
    finally:
        policy_slots.release()
        completed.set()
```

- [ ] **Step 3: Wire kwargs into each curl hop and remove duplicate redirect DNS**

In `_resolve_short_share_url()`, reject explicit proxies before transport, use the direct proxy mapping, store the worker result, and expand it into `curl_get`:

```python
proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
if str(proxy or "").strip():
    raise CurlRequestsError("short-link pinned DNS unavailable with configured proxy")
proxies = requests_proxy_mapping()

request_kwargs = self._restricted_short_link_request_kwargs(
    current_url,
    deadline=deadline,
)

response = curl_get(
    current_url,
    headers=self._build_detail_request_headers(),
    timeout=self._short_link_timeout(remaining),
    allow_redirects=False,
    proxies=proxies,
    content_callback=collect_body,
    **request_kwargs,
)
```

Delete the redirect branch's eager `_restricted_short_link_request_kwargs(next_url, deadline=deadline)` call. Keep the platform-host check, close the current response, set `current_url = next_url`, and let the next loop iteration perform the only validation and pin for that hop.

- [ ] **Step 4: Run focused GREEN verification**

Run: `python -m pytest tests/unit/app/spiders/kuaishou/test_share_resolution.py -q`

Expected: every test passes; each curl call has the exact `CurlOpt.RESOLVE` value, proxy/empty/zero-port paths do not call curl, and the HTTP-success run path does not instantiate Playwright.

- [ ] **Step 5: Run lint and the Kuaishou unit suite**

Run:

```powershell
python -m ruff check app/spiders/kuaishou/share_runtime.py tests/unit/app/spiders/kuaishou/test_share_resolution.py
python -m pytest tests/unit/app/spiders/kuaishou -q
```

Expected: Ruff exits 0 and all Kuaishou unit tests pass without new warnings.

- [ ] **Step 6: Commit the isolated implementation**

```powershell
git add app/spiders/kuaishou/share_runtime.py tests/unit/app/spiders/kuaishou/test_share_resolution.py docs/superpowers/specs/2026-07-17-kuaishou-curl-dns-pinning-design.md
git commit -m "fix: pin Kuaishou short-link DNS"
```

Expected: only the three listed files are committed; unrelated dirty files remain unstaged.

### Task 2: Verify repository contracts, review, and publish

**Files:**
- Verify only: `app/spiders/kuaishou/share_runtime.py`
- Verify only: `tests/unit/app/spiders/kuaishou/test_share_resolution.py`
- Verify only: `tests/architecture/test_test_suite_layout.py`
- Verify only: `tests/testkit/test_catalog.py`

**Interfaces:**
- Consumes: the completed Task 1 implementation and the directory-driven test catalog.
- Produces: evidence that the hotfix is isolated, classified correctly, regression-safe, and present on `origin/main`.

- [ ] **Step 1: Run security-adjacent and taxonomy regressions**

```powershell
python -m pytest tests/unit/app/spiders/kuaishou tests/unit/shared/test_runtime_helpers.py tests/unit/shared/network/test_resilient_dns.py -q
python -m pytest tests/architecture/test_test_suite_layout.py tests/architecture/test_file_size_limits.py tests/testkit/test_catalog.py -q
python tests/launcher.py --list
```

Expected: all pytest commands pass; the launcher lists all eight built-in suites and no unclassified test.

- [ ] **Step 2: Verify collection and the affected unit namespace**

```powershell
python -m pytest tests --collect-only -q
python -m pytest tests/unit/app/spiders/kuaishou -q
```

Expected: collection exits 0 without marker or naming errors, and the Kuaishou suite is green.

- [ ] **Step 3: Review the exact diff and scope**

```powershell
git diff --check
git diff -- app/spiders/kuaishou/share_runtime.py tests/unit/app/spiders/kuaishou/test_share_resolution.py docs/superpowers/specs/2026-07-17-kuaishou-curl-dns-pinning-design.md
git status --short
```

Expected: no whitespace errors; only planned files belong to the hotfix; all pre-existing user-modified files remain unstaged and unchanged by this work.

- [ ] **Step 4: Push completed planning and implementation commits**

Run: `git push origin main`

Expected: `origin/main` advances without force push.
