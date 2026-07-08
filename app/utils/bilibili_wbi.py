"""Bilibili WBI request signing helpers."""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Mapping

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

WBI_FILTER_CHARS = "!'()*"


@dataclass(frozen=True)
class BilibiliWbiKeys:
    img_key: str
    sub_key: str


def _extract_key_from_url(url: object) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    tail = text.rsplit("/", 1)[-1]
    return tail.split(".", 1)[0]


def extract_wbi_keys_from_nav_data(nav_data: Mapping[str, Any] | None) -> BilibiliWbiKeys | None:
    """Extract WBI image keys from Bilibili nav payload data."""
    if not isinstance(nav_data, Mapping):
        return None
    wbi_img = nav_data.get("wbi_img")
    if not isinstance(wbi_img, Mapping):
        return None
    img_key = _extract_key_from_url(wbi_img.get("img_url"))
    sub_key = _extract_key_from_url(wbi_img.get("sub_url"))
    if not img_key or not sub_key:
        return None
    return BilibiliWbiKeys(img_key=img_key, sub_key=sub_key)


def make_mixin_key(img_key: str, sub_key: str) -> str:
    """Build the 32-char WBI mixin key from img/sub keys."""
    raw_key = f"{img_key}{sub_key}"
    if len(raw_key) < max(MIXIN_KEY_ENC_TAB) + 1:
        return ""
    return "".join(raw_key[index] for index in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi_params(
    params: Mapping[str, Any] | None,
    img_key: str,
    sub_key: str,
    *,
    now: int | None = None,
) -> dict[str, str]:
    """Return params with Bilibili WBI `wts` and `w_rid` applied."""
    mixin_key = make_mixin_key(img_key, sub_key)
    if not mixin_key:
        return {str(key): str(value) for key, value in dict(params or {}).items()}

    signed_params: dict[str, str] = {
        str(key): "".join(ch for ch in str(value) if ch not in WBI_FILTER_CHARS)
        for key, value in dict(params or {}).items()
    }
    signed_params["wts"] = str(int(time.time() if now is None else now))
    sorted_params = dict(sorted(signed_params.items()))
    query = urllib.parse.urlencode(sorted_params)
    signed_params["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode("utf-8")).hexdigest()
    return signed_params


class BilibiliWbiSigner:
    """Thread-safe WBI key cache and signer for sync requests."""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = max(60, int(ttl_seconds or 3600))
        self._lock = threading.RLock()
        self._keys: BilibiliWbiKeys | None = None
        self._expires_at = 0.0

    def clear(self) -> None:
        with self._lock:
            self._keys = None
            self._expires_at = 0.0

    def set_keys(self, img_key: str, sub_key: str, *, ttl_seconds: int | None = None) -> None:
        with self._lock:
            self._keys = BilibiliWbiKeys(str(img_key), str(sub_key))
            ttl = self.ttl_seconds if ttl_seconds is None else max(60, int(ttl_seconds))
            self._expires_at = time.monotonic() + ttl

    def update_from_nav_data(self, nav_data: Mapping[str, Any] | None) -> bool:
        keys = extract_wbi_keys_from_nav_data(nav_data)
        if keys is None:
            return False
        self.set_keys(keys.img_key, keys.sub_key)
        return True

    def current_keys(self) -> BilibiliWbiKeys | None:
        with self._lock:
            if self._keys is None or time.monotonic() >= self._expires_at:
                return None
            return self._keys

    def _fetch_keys(
        self,
        request_get: Callable[..., Any] | None,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | int | None = 15,
        proxies: Mapping[str, str] | None = None,
    ) -> BilibiliWbiKeys | None:
        if request_get is None:
            return None
        try:
            kwargs: dict[str, Any] = {"timeout": timeout}
            if headers:
                kwargs["headers"] = dict(headers)
            if proxies:
                kwargs["proxies"] = dict(proxies)
            response = request_get(NAV_URL, **kwargs)
            payload = response.json()
            data = payload.get("data", payload) if isinstance(payload, Mapping) else None
            keys = extract_wbi_keys_from_nav_data(data)
            if keys is not None:
                self.set_keys(keys.img_key, keys.sub_key)
            return keys
        except Exception:
            return None

    def ensure_keys(
        self,
        request_get: Callable[..., Any] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | int | None = 15,
        proxies: Mapping[str, str] | None = None,
    ) -> BilibiliWbiKeys | None:
        keys = self.current_keys()
        if keys is not None:
            return keys
        with self._lock:
            keys = self.current_keys()
            if keys is not None:
                return keys
            return self._fetch_keys(request_get, headers=headers, timeout=timeout, proxies=proxies)

    def sign_params(
        self,
        params: Mapping[str, Any] | None,
        *,
        request_get: Callable[..., Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | int | None = 15,
        proxies: Mapping[str, str] | None = None,
        now: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        keys = self.ensure_keys(request_get, headers=headers, timeout=timeout, proxies=proxies)
        if keys is None:
            return dict(params or {}), False
        return sign_wbi_params(params, keys.img_key, keys.sub_key, now=now), True


BILIBILI_WBI_SIGNER = BilibiliWbiSigner()
