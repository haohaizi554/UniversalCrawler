from __future__ import annotations

from app.services.frontend_event_aggregator import (
    FrontendEventAggregator,
    FrontendEventPriority,
    sections_for_topic,
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

def test_normal_event_does_not_displace_queued_critical_when_full():
    aggregator = FrontendEventAggregator(max_pending_events=1)

    aggregator.record("task_finished", {"video_id": "done"})
    aggregator.record("settings.update", {"section": "download"})

    state = aggregator.peek()

    assert state.priority == FrontendEventPriority.CRITICAL
    assert len(state.pending_events) == 1
    assert state.pending_events[0]["topic"] == "task_finished"
    assert state.dropped_count == 1
    assert "settings_snapshot" in state.changed_sections

def test_critical_event_displaces_queued_normal_when_full():
    aggregator = FrontendEventAggregator(max_pending_events=1)

    aggregator.record("settings.update", {"section": "download"})
    aggregator.record("task_error", {"video_id": "failed"})

    state = aggregator.peek()

    assert state.priority == FrontendEventPriority.CRITICAL
    assert len(state.pending_events) == 1
    assert state.pending_events[0]["topic"] == "task_error"
    assert state.dropped_count == 1

def test_remove_event_tracks_deleted_ids():
    aggregator = FrontendEventAggregator()

    aggregator.record("video_removed", {"video_id": "gone"})

    state = aggregator.peek()

    assert state.deleted_ids == ("gone",)
    assert "queue_items" in state.changed_sections

def test_metadata_event_refreshes_completed_section_only():
    aggregator = FrontendEventAggregator()

    aggregator.record("videos.metadata", {"video_id": "done", "metadata": True})
    state = aggregator.peek()

    assert sections_for_topic("videos.metadata") == frozenset({"completed_items", "app_status"})
    assert state.changed_sections == frozenset({"completed_items", "app_status"})
    assert state.priority == FrontendEventPriority.NORMAL

def test_sections_since_returns_only_changes_after_base_version():
    aggregator = FrontendEventAggregator()

    aggregator.record("settings.update", {"section": "download"})
    base_version = aggregator.version
    aggregator.record("video_state_changed", {"video_id": "v1", "progress": 20})

    assert aggregator.sections_since(base_version) == frozenset({"active_downloads", "app_status"})


def test_settings_update_includes_settings_contract_section():
    assert sections_for_topic("settings.update") == frozenset(
        {"settings_snapshot", "settings_contract", "download_options", "app_status"},
    )
    assert sections_for_topic("config") == frozenset(
        {"settings_snapshot", "settings_contract", "download_options", "app_status"},
    )

def test_deleted_ids_since_ignores_acknowledged_deletions():
    aggregator = FrontendEventAggregator()

    aggregator.record("video_removed", {"video_id": "old"})
    base_version = aggregator.version
    aggregator.record("video_removed", {"video_id": "new"})

    assert aggregator.deleted_ids_since(base_version) == ("new",)

def test_log_events_are_coalesced_but_keep_versioned_sections():
    aggregator = FrontendEventAggregator()

    aggregator.record("log", {"trace_id": "trace-1", "message": "first"})
    base_version = aggregator.version
    state = aggregator.record("log", {"trace_id": "trace-1", "message": "second"})

    assert state.coalesced_count == 1
    assert len(state.pending_events) == 1
    assert state.pending_events[0]["payload"]["message"] == "second"
    assert aggregator.sections_since(base_version) == frozenset({"log_items", "app_status"})
