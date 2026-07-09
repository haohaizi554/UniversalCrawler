from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from app.services.frontend_log_cache import FrontendLogCache


class FakeCacheService:
    def __init__(self) -> None:
        self.values = {}
        self.deleted = []
        self.persist_flags = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, *, ttl_seconds=None, persist=False):
        self.values[key] = list(value)
        self.persist_flags[key] = persist

    def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)


def test_log_cache_initial_read_is_capped_by_backfill_limit():
    cache_service = FakeCacheService()
    calls = []

    def reader(*, limit):
        calls.append(limit)
        return [{"message": f"file-{index}"} for index in range(limit)]

    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=reader,
        limit_provider=lambda: 1000,
        backfill_limit=200,
        ttl_seconds=60,
    )

    items = cache.merged_items([])

    assert calls == [200]
    assert len(items) == 200


def test_log_cache_growing_limit_does_not_backfill_until_ttl_expires():
    cache_service = FakeCacheService()
    current_limit = 100
    calls = []

    def reader(*, limit):
        calls.append(limit)
        return [{"message": f"file-{index}"} for index in range(limit)]

    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=reader,
        limit_provider=lambda: current_limit,
        backfill_limit=500,
        ttl_seconds=60,
    )

    assert len(cache.merged_items([])) == 100
    current_limit = 500

    assert len(cache.merged_items([])) == 100
    assert calls == [100]


def test_log_cache_shrinking_limit_drops_cached_tail_immediately():
    cache_service = FakeCacheService()
    current_limit = 500

    def reader(*, limit):
        return [{"message": f"file-{index}"} for index in range(limit)]

    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=reader,
        limit_provider=lambda: current_limit,
        backfill_limit=500,
        ttl_seconds=60,
    )

    assert len(cache.merged_items([])) == 500
    cache.resize_limit(100)
    current_limit = 100
    items = cache.merged_items([])

    assert len(items) == 100
    assert items[0]["message"] == "file-400"


def test_log_cache_invalidate_deletes_legacy_and_limit_cache_keys():
    cache_service = FakeCacheService()
    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=lambda *, limit: [],
        limit_provider=lambda: 300,
    )

    cache.invalidate(limit=500)

    assert "frontend.file_log_cache" in cache_service.deleted
    assert "frontend.file_log_cache.500" in cache_service.deleted


def test_worker_log_cache_does_not_read_synchronously_from_snapshot_path():
    cache_service = FakeCacheService()
    calls = []
    reader_started = threading.Event()
    release_reader = threading.Event()

    def reader(*, limit):
        reader_started.set()
        release_reader.wait(timeout=2)
        calls.append(limit)
        return [{"message": f"file-{index}"} for index in range(limit)]

    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=reader,
        limit_provider=lambda: 100,
        worker_enabled=True,
        ttl_seconds=60,
    )
    try:
        assert cache.merged_items([]) == []
        assert calls == []
        assert reader_started.wait(timeout=2)
        assert calls == []
        release_reader.set()
        assert cache.wait_for_idle(timeout=2)

        items = cache.merged_items([])
    finally:
        cache.shutdown()

    assert calls == [100]
    assert len(items) == 100


def test_worker_log_cache_survives_refresh_failure():
    cache_service = FakeCacheService()
    calls = []
    release_first_reader = threading.Event()

    def reader(*, limit):
        calls.append(limit)
        if len(calls) == 1:
            release_first_reader.set()
            raise RuntimeError("transient parse failure")
        return [{"message": f"file-{index}"} for index in range(limit)]

    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=reader,
        limit_provider=lambda: 100,
        worker_enabled=True,
        ttl_seconds=0,
    )
    try:
        cache.request_refresh(100)
        assert release_first_reader.wait(timeout=2)
        assert cache.wait_for_idle(timeout=2)
        assert cache.items_snapshot == []

        cache.request_refresh(100)
        assert cache.wait_for_idle(timeout=2)
        items = cache.items_snapshot
    finally:
        cache.shutdown()

    assert calls == [100, 100]
    assert len(items) == 100


def test_log_cache_invalidate_downgrades_cache_delete_failure():
    class FailingDeleteCache(FakeCacheService):
        def delete(self, key):
            self.deleted.append(key)
            raise RuntimeError("locked cache")

    cache_service = FailingDeleteCache()
    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=lambda *, limit: [],
        limit_provider=lambda: 300,
    )

    cache.invalidate(limit=500)

    assert cache_service.deleted == ["frontend.file_log_cache", "frontend.file_log_cache.500"]


def test_log_cache_read_failure_downgrades_to_source_read():
    class FailingReadCache(FakeCacheService):
        def get(self, key, default=None):
            raise RuntimeError("cache read failed")

    cache_service = FailingReadCache()
    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=lambda *, limit: [{"message": "from-source"}],
        limit_provider=lambda: 100,
    )

    with patch("app.services.frontend_log_cache.debug_logger.log_exception") as log_exception:
        items = cache.refresh_now()

    assert items == [{"message": "from-source"}]
    assert cache.items_snapshot == [{"message": "from-source"}]
    assert log_exception.call_args.args[:2] == ("FrontendLogCache", "read_cache")


def test_log_cache_write_failure_keeps_worker_batch_in_memory():
    class FailingWriteCache(FakeCacheService):
        def set(self, key, value, *, ttl_seconds=None, persist=False):
            raise RuntimeError("cache write failed")

    cache_service = FailingWriteCache()
    cache = FrontendLogCache(
        cache_service=cache_service,
        reader=lambda *, limit: [{"message": "from-source"}],
        limit_provider=lambda: 100,
    )

    with patch("app.services.frontend_log_cache.debug_logger.log_exception") as log_exception:
        items = cache.refresh_now()

    assert items == [{"message": "from-source"}]
    assert cache.items_snapshot == [{"message": "from-source"}]
    assert log_exception.call_args.args[:2] == ("FrontendLogCache", "write_cache")


def test_tail_log_reader_refreshes_appended_entries(tmp_path):
    cache_service = FakeCacheService()
    log_file = Path(tmp_path) / "latest_debug.log"
    log_file.write_text(
        "\n".join(
            [
                "[2026-06-30 10:00:00] [INFO] Test / old-0",
                "[2026-06-30 10:00:01] [INFO] Test / old-1",
            ]
        ),
        encoding="utf-8",
    )
    cache = FrontendLogCache(
        cache_service=cache_service,
        log_path_provider=lambda: log_file,
        limit_provider=lambda: 100,
    )

    initial = cache.refresh_now()
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("\n[2026-06-30 10:00:02] [ERROR] Test / new-2\n")
    updated = cache.refresh_now()

    assert [item["message_summary"] for item in initial] == ["old-0", "old-1"]
    assert [item["message_summary"] for item in updated] == ["old-0", "old-1", "new-2"]


def test_tail_log_cache_persists_parsed_state_with_file_identity(tmp_path):
    cache_service = FakeCacheService()
    log_file = Path(tmp_path) / "latest_debug.log"
    log_file.write_text("[2026-06-30 10:00:00] [INFO] Test / cached\n", encoding="utf-8")
    cache = FrontendLogCache(
        cache_service=cache_service,
        log_path_provider=lambda: log_file,
        limit_provider=lambda: 100,
    )

    items = cache.refresh_now()

    tail_keys = [key for key in cache_service.values if key.startswith("frontend.file_log_cache.tail.")]
    assert len(tail_keys) == 1
    assert cache_service.persist_flags[tail_keys[0]] is True
    assert [item["message_summary"] for item in items] == ["cached"]


def test_tail_log_cache_replaces_stale_persistent_tail_keys(tmp_path):
    cache_service = FakeCacheService()
    log_file = Path(tmp_path) / "latest_debug.log"
    log_file.write_text("[2026-06-30 10:00:00] [INFO] Test / cached\n", encoding="utf-8")
    cache = FrontendLogCache(
        cache_service=cache_service,
        log_path_provider=lambda: log_file,
        limit_provider=lambda: 100,
    )

    cache.refresh_now()
    initial_keys = [key for key in cache_service.values if key.startswith("frontend.file_log_cache.tail.")]
    assert len(initial_keys) == 1
    initial_key = initial_keys[0]

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("[2026-06-30 10:00:01] [INFO] Test / appended\n")
    updated = cache.refresh_now()

    tail_keys = [key for key in cache_service.values if key.startswith("frontend.file_log_cache.tail.")]
    assert len(tail_keys) == 1
    assert tail_keys[0] != initial_key
    assert initial_key in cache_service.deleted
    assert [item["message_summary"] for item in updated] == ["cached", "appended"]


def test_tail_log_cache_hit_hydrates_reader_without_reparsing(tmp_path):
    cache_service = FakeCacheService()
    log_file = Path(tmp_path) / "latest_debug.log"
    log_file.write_text("[2026-06-30 10:00:00] [INFO] Test / cached\n", encoding="utf-8")
    first_cache = FrontendLogCache(
        cache_service=cache_service,
        log_path_provider=lambda: log_file,
        limit_provider=lambda: 100,
    )
    first_cache.refresh_now()

    second_cache = FrontendLogCache(
        cache_service=cache_service,
        log_path_provider=lambda: log_file,
        limit_provider=lambda: 100,
    )
    with patch("app.services.frontend_log_cache.log_adapter.parse_debug_log_text") as parse_debug_log_text:
        parse_debug_log_text.side_effect = AssertionError("cache hit should not parse the file")
        cached = second_cache.refresh_now()

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("[2026-06-30 10:00:01] [INFO] Test / appended\n")
    updated = second_cache.refresh_now()

    assert [item["message_summary"] for item in cached] == ["cached"]
    assert [item["message_summary"] for item in updated] == ["cached", "appended"]
