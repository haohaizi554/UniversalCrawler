"""Shared pytest fixtures for test process isolation."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_user_data(tmp_path, monkeypatch):
    """Keep tests from writing default runtime state into the developer workspace.

    Production code deliberately uses the project ``user_data`` directory while
    running from source. Unit tests exercise the same constructors heavily, so a
    default ``FrontendStateService`` or ``FailedRecordStore`` must be redirected
    unless a test explicitly asserts the runtime path policy.
    """

    monkeypatch.setenv("UCRAWL_USER_DATA_ROOT", str(tmp_path / "user_data"))
    yield
