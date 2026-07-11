"""Shared pytest fixtures for test process isolation."""

from __future__ import annotations

import functools

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


@pytest.fixture(autouse=True)
def cleanup_test_owned_background_workers(monkeypatch):
    """Close thread-owning objects created by each test.

    These workers keep bound callbacks, so relying on garbage collection leaves
    the owning service reachable from its own thread. A long full-suite run can
    otherwise accumulate hundreds of workers before the first native Qt test.
    """
    from app.core.event_bus import EventBus
    from app.services.frontend_state_service import FrontendStateService
    from app.ui.viewmodels.latest_worker import LatestRequestWorker
    from app.ui.viewmodels.sequential_worker import SequentialRequestWorker

    tracked: list[tuple[object, str]] = []

    def track_instances(owner_type, cleanup_method: str) -> None:
        original_init = owner_type.__init__

        @functools.wraps(original_init)
        def tracked_init(instance, *args, **kwargs):
            original_init(instance, *args, **kwargs)
            tracked.append((instance, cleanup_method))

        monkeypatch.setattr(owner_type, "__init__", tracked_init)

    track_instances(EventBus, "shutdown")
    track_instances(FrontendStateService, "destroy")
    track_instances(LatestRequestWorker, "shutdown")
    track_instances(SequentialRequestWorker, "shutdown")

    yield

    for instance, cleanup_method in reversed(tracked):
        cleanup = getattr(instance, cleanup_method, None)
        if not callable(cleanup):
            continue
        try:
            cleanup()
        except Exception:
            # Teardown must continue so one malformed fake cannot leak every
            # resource created later in the same test.
            continue
