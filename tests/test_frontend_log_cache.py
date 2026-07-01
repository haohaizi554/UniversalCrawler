from __future__ import annotations

from app.services.frontend_log_cache import FrontendLogCache


class FakeCacheService:
    def __init__(self) -> None:
        self.values = {}
        self.deleted = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, *, ttl_seconds=None, persist=False):
        self.values[key] = list(value)

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
