"""Helpers for defensive Qt slot wrappers."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from app.debug_logger import debug_logger

P = ParamSpec("P")
R = TypeVar("R")


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
                details={"args_count": len(args), "kwargs": sorted(kwargs)},
            )
            return None

    return _wrapped
