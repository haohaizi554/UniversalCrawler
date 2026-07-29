"""Unit contract for best-effort SDK cleanup at non-SDK entry points."""

from __future__ import annotations

import pytest

from unittest.mock import Mock


def test_close_sdk_once_treats_only_literal_true_as_complete() -> None:
    from shared.sdk_cleanup import close_sdk_once

    sdk = Mock()
    sdk.close.return_value = False

    cleanup_error = close_sdk_once(sdk)

    assert isinstance(cleanup_error, RuntimeError)
    assert "did not complete" in str(cleanup_error)
    sdk.close.assert_called_once_with()


@pytest.mark.parametrize(
    "cleanup_error",
    (
        KeyboardInterrupt("cleanup interrupted"),
        SystemExit(7),
        GeneratorExit("cleanup stopped"),
    ),
)
def test_close_sdk_once_captures_control_flow_without_reinvoking_close(
    cleanup_error: BaseException,
) -> None:
    from shared.sdk_cleanup import close_sdk_once

    sdk = Mock()
    sdk.close.side_effect = cleanup_error

    assert close_sdk_once(sdk) is cleanup_error
    sdk.close.assert_called_once_with()


def test_cleanup_annotation_survives_hostile_metadata() -> None:
    from shared.sdk_cleanup import attach_sdk_cleanup_failure

    class HostilePrimary(KeyboardInterrupt):
        def __getattribute__(self, name: str):
            if name == "add_note":
                raise SystemExit("hostile add_note lookup")
            return super().__getattribute__(name)

        def __setattr__(self, name: str, value: object) -> None:
            if name == "_ucrawl_sdk_cleanup_error":
                raise GeneratorExit("hostile cleanup state")
            super().__setattr__(name, value)

    class HostileCleanup(RuntimeError):
        def __str__(self) -> str:
            raise KeyboardInterrupt("hostile cleanup text")

    primary = HostilePrimary("operation interrupted")

    attach_sdk_cleanup_failure(primary, HostileCleanup())

    assert type(primary) is HostilePrimary


def test_cleanup_diagnostic_has_a_safe_fallback_for_hostile_text() -> None:
    from shared.sdk_cleanup import describe_sdk_cleanup_failure

    class HostileCleanup(RuntimeError):
        def __str__(self) -> str:
            raise SystemExit("hostile cleanup text")

    diagnostic = describe_sdk_cleanup_failure(HostileCleanup())

    assert diagnostic == "UcrawlSDK cleanup failed with HostileCleanup"


def test_cleanup_diagnostic_writer_cannot_replace_a_semantic_outcome() -> None:
    from shared.sdk_cleanup import write_sdk_cleanup_diagnostic

    class HostileStream:
        def write(self, _value: str) -> None:
            raise KeyboardInterrupt("hostile stderr")

    write_sdk_cleanup_diagnostic(
        RuntimeError("cleanup unavailable"),
        stream=HostileStream(),
    )
