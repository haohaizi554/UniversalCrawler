"""Streaming GitHub release-asset transport with bounded progress callbacks."""

from __future__ import annotations

import math
import mimetypes
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

import requests


_UPLOAD_PATH_PATTERN = re.compile(
    r"^/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/[0-9]+/assets$"
)
_TRANSIENT_UPLOAD_STATUS_CODES = frozenset({408, 425, 500, 502, 503, 504})
_DEFAULT_CHUNK_SIZE = 256 * 1024
_DEFAULT_PROGRESS_INTERVAL_SECONDS = 0.25
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 30.0

UploadProgressCallback = Callable[[int, int, float], None]


class UploadTransportError(RuntimeError):
    """Describe a sanitized upload failure without retaining response secrets."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = bool(transient)


class _ProgressReader:
    """Expose a fixed-length file body while coalescing noisy byte callbacks."""

    def __init__(
        self,
        handle,
        total: int,
        callback: UploadProgressCallback,
        *,
        clock: Callable[[], float],
        interval_seconds: float,
        chunk_size: int,
    ) -> None:
        self._handle = handle
        self._total = total
        self._callback = callback
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._chunk_size = chunk_size
        self._started_at = clock()
        self._last_report_at = self._started_at
        self._sent = 0
        self._last_reported = -1

    def __len__(self) -> int:
        return self._total

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        request_size = self._chunk_size if size < 0 else min(size, self._chunk_size)
        chunk = self._handle.read(request_size)
        if not chunk:
            self._report(force=True)
            return b""
        self._sent += len(chunk)
        self._report(force=self._sent >= self._total)
        return chunk

    def _report(self, *, force: bool) -> None:
        now = self._clock()
        if not force and now - self._last_report_at < self._interval_seconds:
            return
        if self._sent == self._last_reported:
            return
        elapsed = max(now - self._started_at, 1e-9)
        self._callback(self._sent, self._total, self._sent / elapsed)
        self._last_report_at = now
        self._last_reported = self._sent


class GitHubAssetUploadTransport:
    """POST one release asset while keeping credentials out of process arguments."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        token_provider: Callable[[], str],
        session_factory: Callable[[], object] = requests.Session,
        clock: Callable[[], float] = time.monotonic,
        request_timeout_seconds: float = 2 * 60 * 60.0,
        progress_interval_seconds: float = _DEFAULT_PROGRESS_INTERVAL_SECONDS,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> None:
        timeout = float(request_timeout_seconds)
        interval = float(progress_interval_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("upload timeout must be finite and positive")
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("progress interval must be finite and non-negative")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError("upload chunk size must be a positive integer")
        self._environment = {str(key): str(value) for key, value in environment.items()}
        self._token_provider = token_provider
        self._session_factory = session_factory
        self._clock = clock
        self._request_timeout_seconds = timeout
        self._progress_interval_seconds = interval
        self._chunk_size = chunk_size

    def upload(
        self,
        upload_url: str,
        path: Path,
        on_progress: UploadProgressCallback,
    ) -> None:
        endpoint = _trusted_upload_endpoint(upload_url)
        asset_path = Path(path).resolve(strict=True)
        total = asset_path.stat().st_size
        token = str(self._token_provider() or "").strip()
        if not token:
            raise UploadTransportError("GitHub authentication is unavailable", transient=False)

        session = self._session_factory()
        session.trust_env = False
        response = None
        on_progress(0, total, 0.0)
        try:
            with asset_path.open("rb") as handle:
                body = _ProgressReader(
                    handle,
                    total,
                    on_progress,
                    clock=self._clock,
                    interval_seconds=self._progress_interval_seconds,
                    chunk_size=self._chunk_size,
                )
                try:
                    response = session.post(
                        endpoint,
                        params={"name": asset_path.name},
                        headers={
                            "Accept": "application/vnd.github+json",
                            "Authorization": f"Bearer {token}",
                            "Content-Length": str(total),
                            "Content-Type": mimetypes.guess_type(asset_path.name)[0]
                            or "application/octet-stream",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                        data=body,
                        timeout=(
                            _DEFAULT_CONNECT_TIMEOUT_SECONDS,
                            self._request_timeout_seconds,
                        ),
                        proxies=_request_proxies(self._environment),
                        allow_redirects=False,
                    )
                except requests.RequestException:
                    raise UploadTransportError(
                        "GitHub asset upload connection failed",
                        transient=True,
                    ) from None
            status_code = int(getattr(response, "status_code", 0))
            if status_code != 201:
                raise UploadTransportError(
                    f"GitHub asset upload returned HTTP {status_code}",
                    transient=status_code in _TRANSIENT_UPLOAD_STATUS_CODES,
                )
            try:
                payload = response.json()
            except (TypeError, ValueError):
                raise UploadTransportError(
                    "GitHub asset upload returned an invalid response",
                    transient=False,
                ) from None
            if not isinstance(payload, Mapping) or payload.get("state") != "uploaded":
                raise UploadTransportError(
                    "GitHub asset upload was not finalized",
                    transient=False,
                )
        finally:
            if response is not None:
                response.close()
            close = getattr(session, "close", None)
            if callable(close):
                close()


def _trusted_upload_endpoint(value: str) -> str:
    endpoint = str(value).split("{", 1)[0].strip()
    parsed = urlsplit(endpoint)
    trusted = (
        parsed.scheme == "https"
        and parsed.hostname == "uploads.github.com"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and _UPLOAD_PATH_PATTERN.fullmatch(parsed.path) is not None
    )
    if not trusted:
        raise ValueError("trusted GitHub upload URL is required")
    return endpoint


def _request_proxies(environment: Mapping[str, str]) -> dict[str, str]:
    values = {str(key).casefold(): str(value).strip() for key, value in environment.items()}
    fallback = values.get("all_proxy", "")
    http_proxy = values.get("http_proxy", "") or fallback
    https_proxy = values.get("https_proxy", "") or fallback
    result: dict[str, str] = {}
    if http_proxy:
        result["http"] = http_proxy
    elif https_proxy:
        result["http"] = https_proxy
    if https_proxy:
        result["https"] = https_proxy
    elif http_proxy:
        result["https"] = http_proxy
    return result


__all__ = ["GitHubAssetUploadTransport", "UploadTransportError"]
