"""Failure-safe cleanup helpers for SDK-owning command entry points."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, TextIO

_CLEANUP_ERROR_ATTRIBUTE = "_ucrawl_sdk_cleanup_error"
_INCOMPLETE_MESSAGE = "UcrawlSDK cleanup did not complete"


def safe_exception_text(
    error: BaseException,
    *,
    fallback: str = "unknown error",
) -> str:
    """Describe an exception without trusting its text or type metadata."""

    try:
        detail = str(error)
    except BaseException:
        detail = ""
    if type(detail) is str and detail:
        return detail
    try:
        error_name = type(error).__name__
    except BaseException:
        error_name = ""
    if type(error_name) is str and error_name:
        return error_name
    return fallback


def close_sdk_once(sdk: Any) -> BaseException | None:
    """Close one SDK exactly once and return, rather than raise, its failure."""

    try:
        if sdk.close() is True:
            return None
    except BaseException as cleanup_error:
        return cleanup_error
    return RuntimeError(_INCOMPLETE_MESSAGE)


def describe_sdk_cleanup_failure(cleanup_error: BaseException) -> str:
    """Build a non-throwing diagnostic for an SDK cleanup failure."""

    detail = safe_exception_text(cleanup_error)
    try:
        rendered = str(cleanup_error)
    except BaseException:
        rendered = ""
    if type(rendered) is str and rendered:
        return "UcrawlSDK cleanup failed: " + rendered
    if detail == "unknown error":
        return "UcrawlSDK cleanup failed with unknown error"
    return "UcrawlSDK cleanup failed with " + detail


def attach_sdk_cleanup_failure(
    primary_error: BaseException,
    cleanup_error: BaseException,
) -> None:
    """Best-effort annotation that can never replace the primary exception."""

    note = describe_sdk_cleanup_failure(cleanup_error)
    try:
        add_note = getattr(primary_error, "add_note", None)
    except BaseException:
        add_note = None
    if callable(add_note):
        try:
            add_note(note)
        except BaseException:
            pass
    try:
        setattr(primary_error, _CLEANUP_ERROR_ATTRIBUTE, cleanup_error)
    except BaseException:
        pass


def append_sdk_cleanup_diagnostic(
    primary_message: str | None,
    cleanup_error: BaseException,
) -> str:
    """Append a cleanup diagnostic to a semantic command failure."""

    diagnostic = describe_sdk_cleanup_failure(cleanup_error)
    if type(primary_message) is str and primary_message:
        return primary_message + "\n" + diagnostic
    return diagnostic


def is_sdk_cleanup_control_flow(cleanup_error: BaseException) -> bool:
    """Return whether cleanup raised process/interpreter control flow."""

    return isinstance(
        cleanup_error,
        (KeyboardInterrupt, SystemExit, GeneratorExit),
    )


def write_text_best_effort(stream: TextIO, message: str) -> None:
    """Write a diagnostic without letting a hostile stream change semantics."""

    try:
        stream.write(message)
    except BaseException:
        pass


def call_best_effort(
    callback: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Invoke an output callback without changing an established outcome."""

    try:
        callback(*args, **kwargs)
    except BaseException:
        pass


def write_sdk_cleanup_diagnostic(
    cleanup_error: BaseException,
    *,
    stream: TextIO | None = None,
) -> None:
    """Best-effort cleanup reporting for integer-returning CLI surfaces."""

    target = sys.stderr if stream is None else stream
    write_text_best_effort(
        target,
        describe_sdk_cleanup_failure(cleanup_error) + "\n",
    )
