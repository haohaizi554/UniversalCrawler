"""Minimal environment builders for media helper subprocesses."""

from __future__ import annotations

import os
from collections.abc import Mapping

_SAFE_INHERITED_KEYS = (
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "PATH",
    "PATHEXT",
)
_SENSITIVE_MARKERS = (
    "PROXY",
    "COOKIE",
    "AUTHORIZATION",
    "CREDENTIAL",
    "PASSWORD",
    "TOKEN",
    "SECRET",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.upper()
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def isolated_media_subprocess_env(
    *, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return a minimal environment without proxy or credential inheritance."""

    env: dict[str, str] = {}
    for key in _SAFE_INHERITED_KEYS:
        value = os.environ.get(key)
        if type(value) is str and value:
            env[key] = value
    for key, value in (extra or {}).items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("subprocess environment entries must be strings")
        if _is_sensitive_key(key):
            raise ValueError(f"sensitive subprocess environment key is forbidden: {key}")
        env[key] = value
    return env
