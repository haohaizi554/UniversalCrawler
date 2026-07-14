"""Helpers for defensive Qt slot wrappers."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from app.debug_logger import debug_logger

P = ParamSpec("P")
R = TypeVar("R")
_SENSITIVE_KEY_PARTS = ("api_key", "credential", "password", "secret", "token")


def _slot_kwarg_summary(name: str, value: Any) -> Any:
    normalized_name = str(name).strip().lower()
    if any(part in normalized_name for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 120 else f"{value[:117]}..."
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return f"<{type(value).__name__}>"


def safe_slot(fn: Callable[P, R]) -> Callable[P, R | None]:
    """Log exceptions raised by Qt slots instead of letting them escape Qt."""

    @functools.wraps(fn)
    def _wrapped(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive GUI boundary
            debug_logger.log_exception(
                getattr(fn, "__module__", "QtSlot"),
                getattr(fn, "__qualname__", getattr(fn, "__name__", "slot")),
                exc,
                details={
                    "arg_types": [type(value).__name__ for value in args],
                    "kwargs": {
                        key: _slot_kwarg_summary(key, value)
                        for key, value in sorted(kwargs.items())
                    },
                },
            )
            return None

    return _wrapped
