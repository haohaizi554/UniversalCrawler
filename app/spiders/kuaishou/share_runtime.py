"""Kuaishou short-link and direct-share runtime helpers."""

import json
import re
import threading
import time
import urllib.parse

import requests
from curl_cffi.requests import RequestsError as CurlRequestsError
from curl_cffi.requests import get as curl_get
from playwright.sync_api import Error as PlaywrightError

from shared.network_proxy import requests_proxy_mapping
from shared.runtime_options import DomainPolicyViolation


_SHORT_LINK_POLICY_SLOTS = threading.BoundedSemaphore(2)


class KuaishouShareRuntimeMixin:
    """Own the bounded HTTP path used before browser fallback."""

    def _extract_first_url(self, raw_text: str) -> str:
        """从分享文案中提取第一个 URL；没有则回退原始输入。"""
        raw = str(raw_text or "").strip()
        match = re.search(r"https?://[^\s`，。！？；;,)）\]'\"]+", raw)
        candidate = match.group(0) if match else raw
        return candidate.rstrip("，。！？；;,.!?)）]}'\"")

    def _is_kuaishou_url(self, raw_text: str) -> bool:
        """判断输入是否为快手相关 URL。"""
        return self._url_matches_hosts(
            str(raw_text or ""),
            ("kuaishou.com", "chenzhongtech.com"),
        )

    def _is_detail_url(self, raw_text: str) -> bool:
        """识别快手单条作品详情链接。"""
        if not self._is_kuaishou_url(raw_text):
            return False
        parsed = urllib.parse.urlparse(str(raw_text or ""))
        path = parsed.path.lower()
        query_keys = {key.lower() for key in urllib.parse.parse_qs(parsed.query)}
        return "/short-video/" in path or "/fw/photo/" in path or "photoid" in query_keys

    def _is_short_share_url(self, raw_text: str) -> bool:
        """识别即使 HTTP 展开失败也必须保留分享语义的短链。"""
        if not self._is_kuaishou_url(raw_text):
            return False
        parsed = urllib.parse.urlparse(str(raw_text or "").strip())
        host = (parsed.hostname or "").lower()
        return host == "v.kuaishou.com" or (
            host in {"kuaishou.com", "www.kuaishou.com"}
            and parsed.path.lower().startswith("/f/")
        )

    def _resolve_short_share_url(self, url: str) -> str:
        """将快手短分享链解析为最终详情或主页链接。"""
        candidate = str(url or "").strip()
        if not self._is_short_share_url(candidate):
            return url
        self._close_pending_share_response()
        response = None
        deadline = time.monotonic() + self.SHORT_LINK_TOTAL_TIMEOUT_SECONDS
        try:
            proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
            proxies = requests_proxy_mapping(proxy)
            current_url = candidate
            for redirect_count in range(self.SHORT_LINK_MAX_REDIRECTS + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CurlRequestsError("short-link total timeout")
                self._restricted_short_link_request_kwargs(
                    current_url,
                    deadline=deadline,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CurlRequestsError("short-link total timeout")
                body = bytearray()
                aborted_reason = None

                def collect_body(chunk: bytes) -> int:
                    nonlocal aborted_reason
                    if time.monotonic() >= deadline:
                        aborted_reason = "timeout"
                        return 0
                    if hasattr(self, "_is_running") and not self.is_running:
                        aborted_reason = "cancelled"
                        return 0
                    if (
                        len(body) + len(chunk)
                        > self.SHARE_DETAIL_HTML_MAX_BYTES
                    ):
                        aborted_reason = "oversized"
                        return 0
                    body.extend(chunk)
                    return len(chunk)

                try:
                    response = curl_get(
                        current_url,
                        headers=self._build_detail_request_headers(),
                        timeout=self._short_link_timeout(remaining),
                        allow_redirects=False,
                        proxies=proxies,
                        content_callback=collect_body,
                    )
                except CurlRequestsError:
                    if aborted_reason == "oversized":
                        self.log(
                            "⚠️ 快手分享页 HTML 超过解析预算，将回退浏览器链路"
                        )
                    raise
                try:
                    status_code = int(getattr(response, "status_code", 0) or 0)
                except (TypeError, ValueError):
                    status_code = 0
                headers = getattr(response, "headers", {}) or {}
                location = headers.get("Location") or headers.get("location")
                if (
                    status_code in self._public_domain_policy_engine().REDIRECT_STATUS_CODES
                    and location
                ):
                    if redirect_count >= self.SHORT_LINK_MAX_REDIRECTS:
                        raise requests.TooManyRedirects("short-link redirect limit exceeded")
                    next_url = urllib.parse.urljoin(
                        str(getattr(response, "url", "") or current_url),
                        str(location),
                    )
                    if not self._url_matches_hosts(
                        next_url,
                        ("kuaishou.com", "chenzhongtech.com"),
                    ):
                        raise DomainPolicyViolation("重定向目标不属于目标平台")
                    self._restricted_short_link_request_kwargs(
                        next_url,
                        deadline=deadline,
                    )
                    response.close()
                    response = None
                    current_url = next_url
                    continue

                resolved = str(getattr(response, "url", "") or current_url)
                if self._is_detail_url(resolved):
                    encoding = getattr(response, "encoding", None)
                    if not isinstance(encoding, str) or not encoding:
                        encoding = "utf-8"
                    try:
                        response._ucrawl_bounded_text = body.decode(
                            encoding,
                            errors="replace",
                        )
                    except LookupError:
                        response._ucrawl_bounded_text = body.decode(
                            "utf-8",
                            errors="replace",
                        )
                    self._pending_share_response = (resolved, response, deadline)
                    response = None
                else:
                    response.close()
                    response = None
                self.log(f"🔗 [分享链接解析] {candidate} -> {resolved}")
                return resolved
            raise requests.TooManyRedirects("short-link redirect limit exceeded")
        except (
            requests.RequestException,
            CurlRequestsError,
            DomainPolicyViolation,
            OSError,
        ) as exc:
            if response is not None:
                try:
                    response.close()
                except (
                    AttributeError,
                    OSError,
                    requests.RequestException,
                    CurlRequestsError,
                ):
                    pass
            self.log(f"⚠️ [分享链接解析失败] {exc}")
            return candidate

    def _short_link_timeout(
        self,
        remaining_seconds: float | None = None,
    ) -> tuple[float, float]:
        """限制短链展开的连接和读取等待，不继承页面导航的长超时。"""
        configured = max(1.0, float(self._configured_timeout_seconds(default=60)))
        connect_cap = min(configured, self.SHORT_LINK_CONNECT_TIMEOUT_SECONDS)
        read_cap = min(configured, self.SHORT_LINK_READ_TIMEOUT_SECONDS)
        if remaining_seconds is None:
            return connect_cap, read_cap
        remaining = max(0.05, float(remaining_seconds))
        connect_timeout = min(connect_cap, max(0.01, remaining / 3))
        read_timeout = min(
            read_cap,
            max(0.01, remaining - connect_timeout),
        )
        return connect_timeout, read_timeout

    def _restricted_short_link_request_kwargs(
        self,
        url: str,
        *,
        deadline: float,
    ) -> dict[str, object]:
        """Validate an SSRF-sensitive short-link hop within its total deadline."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CurlRequestsError("short-link public URL validation timeout")
        policy_slots = _SHORT_LINK_POLICY_SLOTS
        if not policy_slots.acquire(timeout=remaining):
            raise CurlRequestsError("short-link public URL validation timeout")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            policy_slots.release()
            raise CurlRequestsError("short-link public URL validation timeout")

        completed = threading.Event()
        result: dict[str, object] = {}

        def validate() -> None:
            try:
                result["value"] = self._restricted_public_request_kwargs(
                    url,
                    allowed_hosts=("kuaishou.com", "chenzhongtech.com"),
                )
            except Exception as exc:
                result["error"] = exc
            finally:
                policy_slots.release()
                completed.set()

        worker = threading.Thread(
            target=validate,
            name="kuaishou-short-link-policy",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            policy_slots.release()
            raise CurlRequestsError(
                "short-link public URL validation unavailable"
            ) from exc
        if not completed.wait(timeout=remaining):
            raise CurlRequestsError("short-link public URL validation timeout")
        error = result.get("error")
        if isinstance(error, Exception):
            raise error
        value = result.get("value")
        return value if isinstance(value, dict) else {}

    def _close_pending_share_response(self) -> None:
        """关闭尚未被详情解析消费的流式短链响应。"""
        pending = getattr(self, "_pending_share_response", None)
        self._pending_share_response = None
        if not pending:
            return
        _resolved_url, response, *_deadline = pending
        try:
            response.close()
        except (
            AttributeError,
            OSError,
            requests.RequestException,
            CurlRequestsError,
        ):
            pass

    def _take_pending_share_response(self, detail_url: str):
        """取得与目标详情 URL 匹配的短链最终响应，并关闭过期缓存。"""
        pending = getattr(self, "_pending_share_response", None)
        self._pending_share_response = None
        if not pending:
            return None
        resolved_url, response, *deadline_values = pending
        deadline = deadline_values[0] if deadline_values else None
        if str(resolved_url or "").strip() == str(detail_url or "").strip():
            return response, deadline
        try:
            response.close()
        except (
            AttributeError,
            OSError,
            requests.RequestException,
            CurlRequestsError,
        ):
            pass
        return None

    def _normalize_keyword(self, raw_text: str) -> str:
        """兼容分享文案、短链和完整快手链接。"""
        extracted = self._extract_first_url(raw_text)
        return self._resolve_short_share_url(extracted)

    def _build_detail_request_headers(self) -> dict[str, str]:
        """构建分享详情页直连请求头。"""
        return {
            "User-Agent": self._user_agent(),
            "Referer": "https://www.kuaishou.com/",
        }

    def _read_bounded_response_text(
        self,
        response,
        *,
        deadline: float | None = None,
    ) -> str:
        """流式读取详情 HTML，并在超过预算时立即放弃浏览器外解析。"""
        preloaded = getattr(response, "_ucrawl_bounded_text", None)
        if isinstance(preloaded, str):
            return preloaded
        payload = bytearray()
        chunks = iter(
            response.iter_content(
                chunk_size=64 * 1024,
                decode_unicode=False,
            )
        )
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                self.log("⚠️ 快手分享页读取超过总时间预算，将回退浏览器链路")
                return ""
            if hasattr(self, "_is_running") and not self.is_running:
                return ""
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            if deadline is not None and time.monotonic() >= deadline:
                self.log("⚠️ 快手分享页读取超过总时间预算，将回退浏览器链路")
                return ""
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            if len(payload) + len(chunk) > self.SHARE_DETAIL_HTML_MAX_BYTES:
                self.log("⚠️ 快手分享页 HTML 超过解析预算，将回退浏览器链路")
                return ""
            payload.extend(chunk)
        encoding = getattr(response, "encoding", None)
        if not isinstance(encoding, str) or not encoding:
            encoding = "utf-8"
        try:
            return payload.decode(encoding, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")

    def _extract_detail_id(self, url: str) -> str:
        """从快手详情链接中提取作品 ID。"""
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        if "photoId" in params:
            return params.get("photoId", [""])[0]
        path = parsed.path.rstrip("/")
        if "/short-video/" in path or "/fw/photo/" in path:
            return path.split("/")[-1]
        return ""

    def _extract_state_blob(self, html: str, prefix: str, suffix: str = "</script>") -> str:
        """从 HTML 中抽取指定状态脚本文本。"""
        if not html or prefix not in html:
            return ""
        start = html.find(prefix)
        if start < 0:
            return ""
        start += len(prefix)
        end = html.find(suffix, start)
        blob = html[start:end] if end >= 0 else html[start:]
        return blob.strip()

    def _load_json_blob(self, blob: str) -> dict:
        """尽量用 JSON 解析页面状态；失败时返回空字典。"""
        if not blob:
            return {}
        cleaned = blob.replace(
            ";(function(){var s;(s=document.currentScript||document.scripts[document.scripts.length-1]).parentNode.removeChild(s);}());",
            "",
        ).rstrip(" ;")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}

    def _extract_apollo_video_detail(self, payload: dict, detail_id: str) -> tuple[str, str]:
        """从 __APOLLO_STATE__ 中提取标题和直链。"""
        client = payload.get("defaultClient", {}) if isinstance(payload, dict) else {}
        detail = client.get(f"VisionVideoDetailPhoto:{detail_id}", {}) if isinstance(client, dict) else {}
        if not isinstance(detail, dict):
            return "", ""
        title = str(detail.get("caption") or "").strip()
        media_url = str(detail.get("photoUrl") or "").strip()
        return title, media_url

    def _fetch_share_detail_via_http(self, detail_url: str) -> tuple[str, str]:
        """通过纯 HTTP 抓取快手分享/详情页，避免弹浏览器。"""
        pending = self._take_pending_share_response(detail_url)
        response = None
        deadline = None
        if pending is not None:
            response, deadline = pending
        try:
            if response is None:
                deadline = (
                    time.monotonic()
                    + self._configured_timeout_seconds(default=60)
                )
                request_kwargs = self._restricted_public_request_kwargs(
                    detail_url,
                    allowed_hosts=("kuaishou.com", "chenzhongtech.com"),
                )
                proxy = self._effective_proxy_server((getattr(self, "config", {}) or {}).get("proxy"))
                proxies = requests_proxy_mapping(proxy)
                response = requests.get(
                    detail_url,
                    headers=self._build_detail_request_headers(),
                    timeout=self._configured_timeout_seconds(default=60),
                    allow_redirects=True,
                    stream=True,
                    proxies=proxies,
                    **request_kwargs,
                )
            response.raise_for_status()
            detail_id = self._extract_detail_id(response.url or detail_url)
            if not detail_id:
                return "", ""

            html = self._read_bounded_response_text(
                response,
                deadline=deadline,
            )
            apollo_blob = self._extract_state_blob(html, "window.__APOLLO_STATE__=")
            if apollo_blob:
                title, media_url = self._extract_apollo_video_detail(self._load_json_blob(apollo_blob), detail_id)
                if media_url:
                    return title or "快手分享作品", media_url

            self.log("⚠️ 快手分享页未解析到 __APOLLO_STATE__ 视频直链，将回退浏览器链路")
            return "", ""
        except (
            requests.RequestException,
            CurlRequestsError,
            DomainPolicyViolation,
        ) as exc:
            self.log(f"⚠️ 快手分享详情页请求失败: {exc}")
            return "", ""
        finally:
            if response is not None:
                try:
                    response.close()
                except (
                    AttributeError,
                    OSError,
                    requests.RequestException,
                    CurlRequestsError,
                ):
                    pass

    def _try_direct_share_download(self) -> bool:
        """分享/详情链接优先走纯 HTTP 快路，成功则不再打开浏览器。"""
        if not self._is_detail_url(self.keyword):
            return False
        self.log("ℹ️ 优先尝试通过 HTTP 快速解析快手分享详情...")
        title, media_url = self._fetch_share_detail_via_http(self.keyword)
        if not media_url:
            return False
        trace_id = self.new_trace_id("share")
        self.debug_state(
            action="emit_share_task_http",
            message="快手分享链接已通过 HTTP 直连解析并提交到下载队列",
            status_code="KUAISHOU_SHARE_TASK_HTTP_EMIT",
            context={"trace_id": trace_id},
            details={"title": title, "stream_url": media_url, "referer": self.keyword},
        )
        self.emit_video(
            url=media_url,
            title=title,
            source="kuaishou",
            meta=self.task_builder.build_download_meta(trace_id, self.keyword, media_url, self._user_agent()),
        )
        self.log(f"✨ 已无浏览器解析分享作品: {title[:24]}...")
        return True

    @staticmethod
    def _share_media_response_url(response) -> str:
        """从详情页响应中筛出可提交给下载器的视频或 HLS 地址。"""
        try:
            url = str(response.url or "").strip()
            content_type = str(response.headers.get("content-type", "") or "").lower()
            resource_type = str(response.request.resource_type or "").lower()
        except (AttributeError, PlaywrightError):
            return ""
        if not url:
            return ""
        path = urllib.parse.urlsplit(url).path.lower()
        if (
            resource_type == "media"
            or content_type.startswith("video/")
            or "mpegurl" in content_type
            or path.endswith(".m3u8")
        ):
            return url
        return ""
