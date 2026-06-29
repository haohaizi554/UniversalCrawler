"""Cross-surface media release coordination for GUI/Web preview handles."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.utils.runtime_paths import user_data_root

_MEDIA_RELEASE_REQUEST_FILE = "media_release_request.json"
_MAX_REQUEST_AGE_SEC = 10.0

def normalize_media_path(path: str | None) -> str | None:
    if not path or not isinstance(path, str):
        return None
    raw = path.strip()
    if not raw:
        return None
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(raw))))
    except (OSError, TypeError, ValueError):
        return os.path.normcase(raw)

@dataclass(slots=True, frozen=True)
class MediaReleaseRequest:
    request_id: str
    local_path: str | None
    created_at: float
    source: str
    reason: str

def _request_file() -> Path:
    return user_data_root() / _MEDIA_RELEASE_REQUEST_FILE

def publish_media_release_request(
    *,
    local_path: str | None,
    source: str,
    reason: str = "delete",
) -> MediaReleaseRequest:
    request = MediaReleaseRequest(
        request_id=uuid.uuid4().hex,
        local_path=normalize_media_path(local_path),
        created_at=time.time(),
        source=source,
        reason=reason,
    )
    path = _request_file()
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "request_id": request.request_id,
        "local_path": request.local_path,
        "created_at": request.created_at,
        "source": request.source,
        "reason": request.reason,
    }
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    return request

def read_media_release_request() -> MediaReleaseRequest | None:
    path = _request_file()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    request_id = payload.get("request_id")
    created_at = payload.get("created_at")
    source = payload.get("source")
    reason = payload.get("reason", "delete")
    if not isinstance(request_id, str) or not request_id:
        return None
    if not isinstance(source, str) or not source:
        return None
    try:
        created_at_value = float(created_at)
    except (TypeError, ValueError):
        return None
    return MediaReleaseRequest(
        request_id=request_id,
        local_path=normalize_media_path(payload.get("local_path")),
        created_at=created_at_value,
        source=source,
        reason=reason if isinstance(reason, str) and reason else "delete",
    )

def poll_media_release_request(last_request_id: str | None) -> tuple[str | None, MediaReleaseRequest | None]:
    request = read_media_release_request()
    if request is None or request.request_id == last_request_id:
        return last_request_id, None
    if time.time() - request.created_at > _MAX_REQUEST_AGE_SEC:
        return request.request_id, None
    return request.request_id, request
