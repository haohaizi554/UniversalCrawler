from __future__ import annotations

from app.services.metadata_retry_tracker import MetadataRetryTracker


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:  # noqa: ANN001
        self.delay = delay
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def _tracker(
    *,
    timers: list[FakeTimer] | None = None,
    events: list[tuple[str, dict]] | None = None,
    retry_result: bool = True,
    max_retries: int = 2,
) -> MetadataRetryTracker:
    timers = timers if timers is not None else []
    events = events if events is not None else []

    def timer_factory(delay, callback):  # noqa: ANN001
        timer = FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    return MetadataRetryTracker(
        retry_callback=lambda _video_id, _source_path: retry_result,
        event_callback=lambda topic, payload: events.append((topic, payload)),
        key_factory=lambda video_id, source_path: f"{video_id}\0{source_path.replace(chr(92), '/')}",
        max_retries_provider=lambda: max_retries,
        delay_provider=lambda: 60.0,
        timer_factory=timer_factory,
    )


def test_empty_failure_count_tracks_and_clears_by_video() -> None:
    tracker = _tracker(max_retries=2)
    key = "v1\0D:/a.mp4"

    assert tracker.record_empty_failure("v1", r"D:\a.mp4") == 1
    assert tracker.exhausted(key) is False
    assert tracker.record_empty_failure("v1", r"D:\a.mp4") == 2
    assert tracker.exhausted(key) is True

    tracker.clear_failures("v1")

    assert tracker.exhausted(key) is False


def test_schedule_deduplicates_and_emits_retry_event() -> None:
    timers: list[FakeTimer] = []
    events: list[tuple[str, dict]] = []
    tracker = _tracker(timers=timers, events=events, retry_result=True)

    tracker.schedule("v1", "D:/a.mp4")
    tracker.schedule("v1", "D:/a.mp4")

    assert len(timers) == 1
    assert timers[0].started is True
    timers[0].callback()

    assert tracker.timers == {}
    assert events == [
        ("videos.metadata", {"video_id": "v1", "metadata": False, "retry": True, "scheduled": True})
    ]


def test_cancel_all_cancels_timers_and_can_clear_failures() -> None:
    timers: list[FakeTimer] = []
    tracker = _tracker(timers=timers)
    tracker.schedule("v1", "D:/a.mp4")
    tracker.record_empty_failure("v1", "D:/a.mp4")

    tracker.cancel_all(clear_failures=True)

    assert timers[0].cancelled is True
    assert tracker.timers == {}
    assert tracker.empty_failures == {}
