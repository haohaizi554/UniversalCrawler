from __future__ import annotations

from app.services.frontend_event_aggregator import (
    FrontendEventAggregator,
    FrontendEventPriority,
)

def test_noisy_progress_events_coalesce_by_video_id():
    aggregator = FrontendEventAggregator()

    aggregator.record("video_state_changed", {"video_id": "v1", "progress": 10})
    aggregator.record("video_state_changed", {"video_id": "v1", "progress": 80})

    state = aggregator.peek()

    assert state.version == 2
    assert state.coalesced_count == 1
    assert len(state.pending_events) == 1
    assert state.pending_events[0]["payload"]["progress"] == 80
    assert "active_downloads" in state.changed_sections

def test_critical_event_survives_noisy_overflow():
    aggregator = FrontendEventAggregator(max_pending_events=1)

    aggregator.record("video_state_changed", {"video_id": "v1", "progress": 10})
    aggregator.record("task_finished", {"video_id": "v1"})

    state = aggregator.peek()

    assert state.priority == FrontendEventPriority.CRITICAL
    assert len(state.pending_events) == 1
    assert state.pending_events[0]["topic"] == "task_finished"
    assert state.dropped_count == 1

def test_remove_event_tracks_deleted_ids():
    aggregator = FrontendEventAggregator()

    aggregator.record("video_removed", {"video_id": "gone"})

    state = aggregator.peek()

    assert state.deleted_ids == ("gone",)
    assert "queue_items" in state.changed_sections
