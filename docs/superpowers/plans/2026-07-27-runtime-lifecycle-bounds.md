# Runtime Lifecycle and Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make shutdown truthfully report quiescence, preserve every accepted local mutation, and cap every retry, timer, metadata, media-release, playback, and subprocess-output structure.

**Architecture:** Runtime owners stop admission before cancellation, drain accepted work, and release state after worker quiescence. Cross-process coordination and playback mutations use transactional SQLite rows; in-memory queues and maps expose fixed capacities and deterministic rejection or eviction rules.

**Tech Stack:** Python 3.10+, threading, asyncio, Qt timers, SQLite/WAL, bounded queues, pytest.

## Global Constraints

- Keep Python 3.10 through 3.13 compatibility.
- Follow `tests/AGENTS.md`; use unit tests for controlled threads/timers and integration tests for real SQLite process boundaries.
- UI and asyncio event-loop threads do not wait on queue capacity, SQLite, subprocess pipes, or worker joins.
- Controller lifecycle capacity is reserved before creation or eviction; overload retains the active controller and returns a stable overload result.
- `stop_all()` reports timeout as non-quiescent; callers do not translate it into a clean shutdown.
- After shutdown admission closes, previously accepted writes drain; new writes fail with a stable exception or false return documented by the owning API.
- Write failures preserve batch order and retry the failed batch before later batches.
- Media-release requests remain durable until the intended consumer acknowledges them.
- Metadata pending entries, retry timers, failure counters, cache entries, and FFmpeg diagnostic bytes have explicit limits.
- Playback mutations from separate processes merge by normalized-path row instead of whole-file replacement.
- Stage and push each task with its exact file list.

---

## File Structure

- Modify `app/web/session_runtime.py`: pre-admitted bounded controller lifecycle/disposal slots and overload semantics.
- Modify `app/services/failed_record_store.py`: accepted-write drain, in-flight accounting, ordered retry, and shutdown result.
- Modify `app/services/media_release_coordination.py`: durable request/consumer-ack tables.
- Modify `app/controllers/application_controller.py`: consume and acknowledge release requests after media handles close.
- Modify `app/core/download_manager_core.py`, `app/controllers/application_lifecycle_mixin.py`, and `app/web/controller.py`: two-phase stop and deferred state disposal.
- Modify `shared/sdk_runtime.py` and `cli/main.py`: idempotent close and `finally` cleanup.
- Modify `app/services/metadata_probe_queue.py`, `app/services/metadata_retry_tracker.py`, and `app/services/media_metadata_service.py`: explicit capacities and shutdown generations.
- Modify `app/core/downloaders/ffmpeg.py`: bounded stderr tail.
- Modify `app/services/playback_position_service.py`: SQLite row store with one-time JSON migration.
- Extend tests under `tests/unit/app/services/`, `tests/unit/app/core/downloaders/`, `tests/unit/app/controllers/`, `tests/unit/app/web/`, `tests/unit/shared/`, and `tests/unit/cli/`.
- Create `tests/integration/app/services/test_runtime_state_concurrency.py` for real shared-database writers.

---

### Task 1: Pre-Admitted Controller Disposal Capacity

**Files:**
- Modify: `app/web/session_runtime.py`
- Modify: `tests/unit/app/web/test_session_runtime.py`

**Interfaces:**
- Produces `ControllerLifecycleAdmission(max_slots: int)` and opaque `ControllerSlot`; a slot is reserved before controller construction and released after shutdown completes.
- Produces disposal states `ACTIVE`, `QUEUED`, `RUNNING`, and `DEFERRED`; one slot moves between states and is never duplicated.
- Produces `WebSessionOverloaded(code="WEB_SESSION_OVERLOADED")` when no slot can be reserved without discarding an active controller.
- Produces metrics `active`, `queued`, `running`, `deferred`, `capacity`, and `overload_count`, with every count read under one lock.

- [ ] **Step 1: Write admission, overload-retention, and total-bound tests**

```python
def test_controller_slot_is_reserved_before_factory_runs():
    timeline = []
    registry = WebSessionRegistry(max_sessions=1, lifecycle_capacity=1)
    registry._controller_factory = lambda: timeline.append(registry.lifecycle_metrics()["reserved"]) or controller()
    registry.get_or_create("first")
    assert timeline == [1]

def test_full_capacity_retains_active_controller_and_reports_overload():
    registry = WebSessionRegistry(max_sessions=1, lifecycle_capacity=1)
    first = registry.get_or_create("first")
    with pytest.raises(WebSessionOverloaded) as captured:
        registry.get_or_create("second")
    assert captured.value.code == "WEB_SESSION_OVERLOADED"
    assert registry.get_or_create("first") is first
    assert registry.session_ids() == ("first",)
    first.controller.shutdown.assert_not_called()

def test_running_queued_and_deferred_never_exceed_total_capacity(registry):
    exercise_concurrent_create_evict_and_shutdown(registry, attempts=100)
    metrics = registry.lifecycle_metrics()
    assert metrics["running"] + metrics["queued"] + metrics["deferred"] <= metrics["capacity"]
    assert metrics["active"] + metrics["running"] + metrics["queued"] + metrics["deferred"] <= metrics["capacity"]

async def test_overload_path_does_not_block_event_loop(full_registry):
    started = time.perf_counter()
    with pytest.raises(WebSessionOverloaded):
        full_registry.get_or_create("new")
    await asyncio.sleep(0)
    assert time.perf_counter() - started < 0.05
```

- [ ] **Step 2: Run focused session tests and confirm RED**

Run: `python -m pytest tests/unit/app/web/test_session_runtime.py -q -k "reserved_before or retains_active or total_capacity or overload_path"`

Expected: assertions fail because disposal capacity is acquired after lookup mutation and saturation can block or orphan a controller.

- [ ] **Step 3: Write slot reservation and atomic lifecycle transitions**

`get_or_create()` reserves a new slot before invoking the controller factory. When the active-session limit requires eviction, it constructs the replacement under its reserved slot, then under the registry/scheduler lock transitions the victim's existing slot `ACTIVE -> QUEUED` or `ACTIVE -> DEFERRED` and swaps lookup entries. If reservation, factory construction, or transition fails, release the new slot, retain the victim in active lookup, and raise `WebSessionOverloaded`.

```python
slot = self._admission.try_reserve(session_id)
if slot is None:
    self._overload_count += 1
    raise WebSessionOverloaded("WEB_SESSION_OVERLOADED")
try:
    replacement = self._build_context(session_id, slot)
    self._swap_with_admitted_disposal(victim, replacement)
except BaseException:
    self._admission.release(slot)
    raise
```

The scheduler uses `put_nowait`; `_deferred` is part of the same capacity accounting, not overflow storage. A context stays in active lookup until its slot transition and scheduler ownership both succeed. Worker completion releases the slot after `controller.shutdown()` returns. `shutdown_all()` returns overload details for contexts it could not transition and never drops their references.

- [ ] **Step 4: Run the full session runtime suite**

Run: `python -m pytest tests/unit/app/web/test_session_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 1**

```bash
git add app/web/session_runtime.py tests/unit/app/web/test_session_runtime.py
git commit -m "fix: admit controller disposal before eviction"
git push origin main
```

### Task 2: Failed-Record Accepted-Write Drain and Ordered Retry

**Files:**
- Modify: `app/services/failed_record_store.py`
- Modify: `tests/unit/app/services/test_failed_record_store.py`

**Interfaces:**
- Produces `FailedRecordStore.shutdown(timeout: float = 5.0) -> bool`; true means no accepted mutation remains queued or in flight and the worker exited.
- Preserves `flush(timeout: float = 2.0) -> bool` with queue-empty and in-flight-empty semantics.
- Changes `queue_upsert(records)` to raise `RuntimeError("failed record store is closing")` after admission closes.

- [ ] **Step 1: Write drain, rejection, and retry-order tests**

```python
def test_shutdown_drains_every_accepted_upsert(tmp_path):
    store = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    for index in range(40):
        store.queue_upsert([{"id": f"video-{index}", "title": str(index)}])
    assert store.shutdown(timeout=2.0) is True
    reopened = FailedRecordStore(db_path=tmp_path / "failed.sqlite3")
    assert reopened.snapshot_total_count() == 40
    assert reopened.shutdown() is True

def test_queue_upsert_rejects_after_shutdown_admission_closes(store):
    assert store.shutdown() is True
    with pytest.raises(RuntimeError, match="failed record store is closing"):
        store.queue_upsert([{"id": "late"}])

def test_failed_batch_retries_before_later_batch(store, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "_write_batch", fail_first_batch_once(calls, failed_id="first"))
    store.queue_upsert([{"id": "first"}])
    store.queue_upsert([{"id": "second"}])
    assert store.flush(timeout=2.0) is True
    assert calls == ["first", "first", "second"]
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_failed_record_store.py -q -k "drains_every or rejects_after or retries_before"`

Expected: assertions fail because shutdown exits before a complete drain and a failed batch is not restored at the front.

- [ ] **Step 3: Write closing, in-flight, and retry state transitions**

```python
def shutdown(self, timeout: float = 5.0) -> bool:
    with self._condition:
        self._accepting = False
        self._drain_requested = True
        self._condition.notify_all()
    return self._worker_stopped.wait(max(0.0, float(timeout)))

def _restore_failed_batch(self, batch: list[dict[str, Any]]) -> None:
    with self._condition:
        self._pending_batches.appendleft(batch)
        self._in_flight_batches -= 1
        self._condition.notify_all()
```

Increment `_in_flight_batches` while holding the condition before removing a batch. Decrement after commit. The worker exits after drain is requested, pending mutation/refresh/prune queues are empty, and `_in_flight_batches == 0`. Use a bounded exponential retry delay capped at 2 seconds and reset it after success.

- [ ] **Step 4: Run the complete failed-record suite**

Run: `python -m pytest tests/unit/app/services/test_failed_record_store.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 2**

```bash
git add app/services/failed_record_store.py tests/unit/app/services/test_failed_record_store.py
git commit -m "fix: drain failed records during shutdown"
git push origin main
```

### Task 3: Durable Media-Release Queue and Consumer Ack

**Files:**
- Modify: `app/services/media_release_coordination.py`
- Modify: `app/controllers/application_controller.py`
- Modify: `tests/unit/app/services/test_media_release_coordination.py`
- Modify: `tests/unit/app/controllers/test_application_controller.py`
- Create: `tests/integration/app/services/test_runtime_state_concurrency.py`

**Interfaces:**
- Produces `MediaConsumerHandle(consumer_id: str, instance_token: str, generation: int)`; token plaintext remains in the player process and SQLite stores its SHA-256 hash.
- Produces `register_media_consumer(consumer_id: str) -> MediaConsumerHandle` and `unregister_media_consumer(handle: MediaConsumerHandle) -> bool` with token-hash/generation CAS.
- Produces `publish_media_release_request(local_path: str, source: str, target_consumer_id: str) -> MediaReleaseRequest`; the transaction snapshots the currently registered target token hash and generation.
- Produces `poll_media_release_requests(handle: MediaConsumerHandle, limit: int = 32) -> Sequence[MediaReleaseRequest]`.
- Produces `ack_media_release_request(request_id: str, handle: MediaConsumerHandle) -> bool` and `is_media_release_acknowledged(request_id: str) -> bool`.

- [ ] **Step 1: Write multi-publisher and ack-order tests**

```python
def test_concurrent_publishers_keep_every_request(shared_release_database):
    consumer = register_media_consumer("desktop-player")
    publish_concurrently(shared_release_database, ["a.mp4", "b.mp4", "c.mp4"])
    pending = poll_media_release_requests(consumer, limit=8)
    assert len(pending) == 3
    assert {Path(item.local_path).name for item in pending} == {"a.mp4", "b.mp4", "c.mp4"}

def test_request_remains_pending_until_matching_consumer_ack(release_store):
    consumer = register_media_consumer("desktop-player")
    request = publish_media_release_request("locked.mp4", "web", consumer.consumer_id)
    forged = dataclasses.replace(consumer, instance_token=secrets.token_urlsafe(32))
    assert ack_media_release_request(request.request_id, forged) is False
    assert [item.request_id for item in poll_media_release_requests(consumer)] == [request.request_id]
    assert ack_media_release_request(request.request_id, consumer) is True
    assert poll_media_release_requests(consumer) == ()

def test_restarted_player_cannot_ack_request_for_previous_generation(release_store):
    previous = register_media_consumer("desktop-player")
    request = publish_media_release_request("locked.mp4", "web", previous.consumer_id)
    assert unregister_media_consumer(previous) is True
    current = register_media_consumer("desktop-player")
    assert current.generation == previous.generation + 1
    assert poll_media_release_requests(current) == ()
    assert ack_media_release_request(request.request_id, current) is False

def test_controller_acks_after_release_callback(controller, release_request):
    controller._poll_external_media_release_requests()
    assert controller.host.release_media_playback.call_count == 1
    assert controller.release_store.ack_calls == [
        (release_request.request_id, controller.media_consumer_handle)
    ]
```

- [ ] **Step 2: Run focused service/controller tests and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_media_release_coordination.py tests/unit/app/controllers/test_application_controller.py tests/integration/app/services/test_runtime_state_concurrency.py -q -k "concurrent_publishers or matching_consumer or previous_generation or acks_after"`

Expected: tests fail because a single JSON slot overwrites requests and acknowledgements are not bound to one player instance generation.

- [ ] **Step 3: Write SQLite request and ack transactions**

```sql
CREATE TABLE media_consumers (
    consumer_id TEXT PRIMARY KEY,
    instance_token_hash TEXT NOT NULL,
    generation INTEGER NOT NULL,
    registered_at REAL NOT NULL
);
CREATE TABLE media_release_requests (
    request_id TEXT PRIMARY KEY,
    normalized_path TEXT NOT NULL,
    source TEXT NOT NULL,
    target_consumer_id TEXT NOT NULL,
    target_instance_token_hash TEXT NOT NULL,
    target_generation INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE media_release_acks (
    request_id TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    instance_token_hash TEXT NOT NULL,
    generation INTEGER NOT NULL,
    acked_at REAL NOT NULL,
    PRIMARY KEY(request_id),
    FOREIGN KEY(request_id) REFERENCES media_release_requests(request_id) ON DELETE CASCADE
);
```

Registration creates a random token and atomically increments the stored generation. Publish fails with `MediaConsumerUnavailable` when no current target exists. Poll and ack hash the caller's token and match consumer ID, token hash, and generation against both the request target and current registration. The controller stores its handle for its lifetime, calls `release_media_playback()`, confirms the normalized path is not active, then acknowledges with that handle. Shutdown unregisters by CAS. A restarted player cannot consume or acknowledge an old generation's request; the publisher receives an unacknowledged timeout and can publish a replacement for the new generation.

- [ ] **Step 4: Run service, controller, and real SQLite tests**

Run: `python -m pytest tests/unit/app/services/test_media_release_coordination.py tests/unit/app/controllers/test_application_controller.py tests/integration/app/services/test_runtime_state_concurrency.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 3**

```bash
git add app/services/media_release_coordination.py app/controllers/application_controller.py tests/unit/app/services/test_media_release_coordination.py tests/unit/app/controllers/test_application_controller.py tests/integration/app/services/test_runtime_state_concurrency.py
git commit -m "fix: persist and acknowledge media release requests"
git push origin main
```

### Task 4: Two-Phase Download and Controller Quiescence

**Files:**
- Modify: `app/core/download_manager_core.py`
- Modify: `app/controllers/application_lifecycle_mixin.py`
- Modify: `app/web/controller.py`
- Modify: `tests/unit/app/core/downloaders/test_manager_core.py`
- Modify: `tests/unit/app/controllers/test_application_lifecycle.py`
- Modify: `tests/unit/app/web/test_controller_runtime.py`

**Interfaces:**
- Produces `StopSummary(accepted: bool, quiescent: bool, timed_out_task_run_ids: Sequence[str])`.
- Produces `DownloadManagerCore.stop_all(timeout_ms: int | None = None) -> StopSummary`.
- Produces controller states `running`, `stopping`, and `stopped`; video/task state is cleared during the `stopping -> stopped` transition.

- [ ] **Step 1: Write timeout truthfulness and deferred-cleanup tests**

```python
def test_stop_all_reports_live_worker_as_non_quiescent(manager, blocking_worker):
    manager.workers.append(blocking_worker)
    result = manager.stop_all(timeout_ms=10)
    assert result == StopSummary(True, False, (blocking_worker.task_run_id,))

def test_desktop_shutdown_keeps_runtime_state_after_stop_timeout(controller):
    controller.download_manager.stop_all.return_value = StopSummary(True, False, ("run-a",))
    controller.shutdown()
    assert controller.lifecycle_state == "stopping"
    controller.host.clear_runtime_state.assert_not_called()

def test_web_shutdown_clears_state_after_waiter_observes_quiescence(web_controller):
    web_controller.download_manager.stop_all.side_effect = [
        StopSummary(True, False, ("run-a",)),
        StopSummary(True, True, ()),
    ]
    web_controller.shutdown()
    web_controller.run_shutdown_waiter()
    assert web_controller.lifecycle_state == "stopped"
    web_controller._clear_video_items.assert_called_once_with()
```

- [ ] **Step 2: Run focused lifecycle tests and confirm RED**

Run: `python -m pytest tests/unit/app/core/downloaders/test_manager_core.py tests/unit/app/controllers/test_application_lifecycle.py tests/unit/app/web/test_controller_runtime.py -q -k "non_quiescent or keeps_runtime or observes_quiescence"`

Expected: assertions fail because `stop_all()` lacks a truthful structured result and controllers clear state before worker exit.

- [ ] **Step 3: Write admission-stop, cancellation, join, and completion phases**

```python
@dataclass(frozen=True)
class StopSummary:
    accepted: bool
    quiescent: bool
    timed_out_task_run_ids: Sequence[str]

def stop_all(self, timeout_ms: int | None = None) -> StopSummary:
    self._accepting_tasks = False
    self._dispatch_stop.set()
    self._cancel_pending_without_dispatch()
    timed_out = self._stop_and_join_workers(self._deadline(timeout_ms))
    quiescent = not timed_out and not self._dispatch_thread.is_alive()
    return StopSummary(True, quiescent, tuple(timed_out))
```

Desktop and Web controllers set `stopping`, schedule a non-UI waiter, and preserve manager-owned collections while non-quiescent. The waiter completes metadata, failed-record, and lease shutdown after downloads and the spider stop. It posts the final `stopped` transition to the owning UI/event-loop thread.

- [ ] **Step 4: Run complete manager and controller suites**

Run: `python -m pytest tests/unit/app/core/downloaders/test_manager_core.py tests/unit/app/controllers/test_application_lifecycle.py tests/unit/app/controllers/test_application_controller.py tests/unit/app/web/test_controller_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 4**

```bash
git add app/core/download_manager_core.py app/controllers/application_lifecycle_mixin.py app/web/controller.py tests/unit/app/core/downloaders/test_manager_core.py tests/unit/app/controllers/test_application_lifecycle.py tests/unit/app/web/test_controller_runtime.py
git commit -m "fix: defer controller cleanup until quiescence"
git push origin main
```

### Task 5: SDK and CLI Guaranteed Cleanup

**Files:**
- Modify: `shared/sdk_runtime.py`
- Modify: `cli/main.py`
- Modify: `tests/unit/shared/test_sdk_runtime.py`
- Modify: `tests/unit/cli/test_main.py`

**Interfaces:**
- Consumes `StopSummary` from Task 4.
- Produces `SdkCloseResult(completed: bool, retryable: bool, stop_summary: StopSummary | None, error_code: str | None)`.
- Produces `UcrawlSDK.close() -> SdkCloseResult`; success is cached and stable, while failure returns to `OPEN` so a later call retries.
- Produces CLI exit code 130 for `KeyboardInterrupt`; close never raises and cannot replace the command's active exception.

- [ ] **Step 1: Write SDK result and CLI exception-path tests**

```python
def test_sdk_close_preserves_non_quiescent_stop_result(sdk):
    expected = StopSummary(True, False, ("run-a",))
    sdk._runner.stop_all.side_effect = [expected, StopSummary(True, True, ())]
    first = sdk.close()
    second = sdk.close()
    third = sdk.close()
    assert (first.completed, first.retryable, first.error_code) == (False, True, "SDK_NOT_QUIESCENT")
    assert second.completed is True
    assert third == second
    assert sdk._runner.stop_all.call_count == 2

def test_sdk_close_exception_is_retryable_and_success_is_stable(sdk):
    sdk._runner.stop_all.side_effect = [RuntimeError("stop failed"), StopSummary(True, True, ())]
    first = sdk.close()
    second = sdk.close()
    third = sdk.close()
    assert (first.completed, first.retryable, first.error_code) == (False, True, "SDK_CLOSE_FAILED")
    assert second.completed is True
    assert third == second
    assert sdk._runner.stop_all.call_count == 2

def test_cli_closes_sdk_after_keyboard_interrupt(monkeypatch):
    sdk = FakeSDK(command_error=KeyboardInterrupt())
    monkeypatch.setattr(cli_main, "UcrawlSDK", lambda: sdk)
    assert cli_main.main(["search", "douyin", "query"]) == 130
    assert sdk.close_calls == 1

def test_cli_closes_sdk_after_command_error(monkeypatch):
    sdk = FakeSDK(
        command_error=RuntimeError("command failed"),
        close_result=SdkCloseResult(False, True, None, "SDK_CLOSE_FAILED"),
    )
    monkeypatch.setattr(cli_main, "UcrawlSDK", lambda: sdk)
    with pytest.raises(RuntimeError, match="command failed"):
        cli_main.main(["search", "douyin", "query"])
    assert sdk.close_calls == 1

def test_keyboard_interrupt_exit_code_survives_close_failure(monkeypatch):
    sdk = FakeSDK(
        command_error=KeyboardInterrupt(),
        close_result=SdkCloseResult(False, True, None, "SDK_CLOSE_FAILED"),
    )
    monkeypatch.setattr(cli_main, "UcrawlSDK", lambda: sdk)
    assert cli_main.main(["search", "douyin", "query"]) == 130
```

- [ ] **Step 2: Run focused SDK/CLI tests and confirm RED**

Run: `python -m pytest tests/unit/shared/test_sdk_runtime.py tests/unit/cli/test_main.py -q -k "non_quiescent or retryable or keyboard_interrupt or command_error or survives_close_failure"`

Expected: assertions fail because close marks itself closed before success, cannot retry, or command paths let close failure replace command outcome.

- [ ] **Step 3: Write idempotent SDK close and CLI `finally` ownership**

```python
def close(self) -> SdkCloseResult:
    with self._close_lock:
        if self._close_state == "CLOSED":
            return self._close_result
        if self._close_state == "CLOSING":
            return SdkCloseResult(False, True, None, "SDK_CLOSE_IN_PROGRESS")
        self._close_state = "CLOSING"
    try:
        summary = self._runner.stop_all() if self._runner is not None else None
    except BaseException:
        result = SdkCloseResult(False, True, None, "SDK_CLOSE_FAILED")
    else:
        completed = summary is None or summary.quiescent
        result = SdkCloseResult(
            completed,
            not completed,
            summary,
            None if completed else "SDK_NOT_QUIESCENT",
        )
    with self._close_lock:
        self._close_result = result
        self._close_state = "CLOSED" if result.completed else "OPEN"
    return result

def main(argv: list[str] | None = None) -> int:
    sdk: UcrawlSDK | None = None
    exit_code = 0
    try:
        sdk = UcrawlSDK()
        exit_code = dispatch_command(parse_args(argv), sdk)
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        if sdk is not None:
            close_result = sdk.close()
            if not close_result.completed:
                log_close_failure(close_result)
    return exit_code
```

`close()` catches and records cleanup exceptions rather than raising. Python preserves any exception propagating through `finally`; the CLI logs the close result and does not `return` or raise from that `finally` block. A normal command success may map an incomplete close to the CLI's documented cleanup-failure exit code in the statement after `finally`; KeyboardInterrupt remains 130.

- [ ] **Step 4: Run complete SDK and CLI suites**

Run: `python -m pytest tests/unit/shared/test_sdk_runtime.py tests/unit/cli/test_main.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 5**

```bash
git add shared/sdk_runtime.py cli/main.py tests/unit/shared/test_sdk_runtime.py tests/unit/cli/test_main.py
git commit -m "fix: close sdk resources on every cli exit"
git push origin main
```

### Task 6: Bounded Metadata and FFmpeg Diagnostic State

**Files:**
- Modify: `app/services/metadata_probe_queue.py`
- Modify: `app/services/metadata_retry_tracker.py`
- Modify: `app/services/media_metadata_service.py`
- Modify: `app/core/downloaders/ffmpeg.py`
- Modify: `tests/unit/app/services/test_metadata_probe_queue.py`
- Modify: `tests/unit/app/services/test_metadata_retry_tracker.py`
- Modify: `tests/unit/app/services/test_media_metadata.py`
- Modify: `tests/integration/app/core/downloaders/test_runtime.py`

**Interfaces:**
- Sets defaults `max_pending=512`, `max_timers=256`, `max_failures=2048`, `max_cache_entries=2048`, and `max_ffmpeg_stderr_bytes=262144`.
- `MetadataProbeQueue.queue()` and `MetadataRetryTracker.schedule()` return bool acceptance.
- Existing keys can be refreshed at capacity; new keys return false.
- Produces `TimerEntry(token: object, generation: int, state: Literal["PENDING_START", "ACTIVE", "FIRED"], timer: Any | None)`; token/generation are visible in `_timers` before `timer.start()`.
- Metadata cache uses least-recently-used eviction; FFmpeg retains the newest bounded stderr tail.

- [ ] **Step 1: Write capacity, timer-failure, LRU, and stderr-tail tests**

```python
def test_probe_queue_rejects_new_key_at_capacity(timer_factory):
    probe_queue = MetadataProbeQueue(timer_factory=timer_factory, max_pending=2)
    assert probe_queue.queue("a", "a.mp4") is True
    assert probe_queue.queue("b", "b.mp4") is True
    assert probe_queue.queue("c", "c.mp4") is False
    assert set(probe_queue.pending) == {"a", "b"}

def test_timer_start_failure_does_not_reserve_slot(failing_timer_factory):
    tracker = MetadataRetryTracker(timer_factory=failing_timer_factory, max_timers=1)
    assert tracker.schedule("a", "a.mp4") is False
    assert tracker.timers == {}

def test_zero_delay_callback_fires_once_without_ghost_timer(zero_delay_timer_factory):
    retries = []
    tracker = MetadataRetryTracker(
        timer_factory=zero_delay_timer_factory,
        retry_callback=lambda video_id, path: retries.append((video_id, path)),
    )
    assert tracker.schedule("a", "a.mp4") is True
    assert retries == [("a", "a.mp4")]
    assert tracker.timers == {}

def test_callback_then_start_error_is_completed_not_ghosted(callback_then_error_factory):
    retries = []
    tracker = MetadataRetryTracker(
        timer_factory=callback_then_error_factory,
        retry_callback=lambda video_id, path: retries.append((video_id, path)),
    )
    assert tracker.schedule("a", "a.mp4") is True
    assert retries == [("a", "a.mp4")]
    assert tracker.timers == {}

def test_callback_from_cancelled_generation_cannot_remove_replacement(controllable_timer_factory):
    tracker = MetadataRetryTracker(timer_factory=controllable_timer_factory)
    tracker.schedule("a", "a.mp4")
    stale_callback = controllable_timer_factory.callbacks[-1]
    tracker.cancel("a")
    tracker.schedule("a", "a.mp4")
    replacement = tracker.timers["a"]
    stale_callback()
    assert tracker.timers["a"] is replacement

def test_metadata_cache_evicts_least_recently_used(service_with_cache):
    service_with_cache.seed(["a", "b"])
    service_with_cache.cached("a")
    service_with_cache.seed(["c"])
    assert service_with_cache.cache_keys == ["a", "c"]

def test_ffmpeg_stderr_tail_is_bounded(ffmpeg_process):
    ffmpeg_process.emit_stderr(b"x" * 400000)
    assert len(ffmpeg_process.stderr_tail) == 262144
    assert ffmpeg_process.stderr_dropped_bytes == 137856
```

- [ ] **Step 2: Run focused bounds tests and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_metadata_probe_queue.py tests/unit/app/services/test_metadata_retry_tracker.py tests/unit/app/services/test_media_metadata.py tests/integration/app/core/downloaders/test_runtime.py -q -k "at_capacity or reserve_slot or zero_delay or callback_then or cancelled_generation or least_recently or stderr_tail"`

Expected: assertions fail because these structures do not enforce the declared capacities.

- [ ] **Step 3: Write deterministic admission, eviction, and generation shutdown**

For queue/retry state, check capacity under the owning lock. Reserve the key by storing a `PENDING_START` entry with token/generation before calling `start()` outside the lock. `_fire()` compares key, object identity, token, and generation, changes the local entry to `FIRED`, removes that exact entry, then calls the retry callback outside the lock. After `start()` returns, change the still-current pending entry to `ACTIVE`; if a zero-delay callback already removed it, report accepted completion. After start failure, remove the still-current pending entry and return false; if the callback already marked the local entry `FIRED`, return true without recreating it.

```python
with self._lock:
    entry = TimerEntry(object(), self._generation, "PENDING_START", None)
    self._timers[key] = entry
timer = self._timer_factory(delay, lambda: self._fire(key, entry.token, entry.generation))
entry.timer = timer
try:
    timer.start()
except BaseException:
    with self._lock:
        if entry.state == "FIRED":
            return True
        if self._timers.get(key) is entry:
            self._timers.pop(key, None)
    return False
with self._lock:
    if self._timers.get(key) is entry:
        entry.state = "ACTIVE"
return True
```

Cap failure counters with oldest-entry eviction. Store metadata cache in `OrderedDict`, move hits to the end, and evict from the front. Shutdown increments generation before cancelling timers; late callbacks from older generations cannot remove or mutate a replacement entry.

Replace the FFmpeg stderr queue with a byte-tail buffer:

```python
def append_stderr(self, chunk: bytes) -> None:
    self._stderr_tail.extend(chunk)
    overflow = len(self._stderr_tail) - self._max_stderr_bytes
    if overflow > 0:
        del self._stderr_tail[:overflow]
        self._stderr_dropped_bytes += overflow
```

- [ ] **Step 4: Run metadata and downloader runtime suites**

Run: `python -m pytest tests/unit/app/services/test_metadata_probe_queue.py tests/unit/app/services/test_metadata_retry_tracker.py tests/unit/app/services/test_media_metadata.py tests/integration/app/core/downloaders/test_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 6**

```bash
git add app/services/metadata_probe_queue.py app/services/metadata_retry_tracker.py app/services/media_metadata_service.py app/core/downloaders/ffmpeg.py tests/unit/app/services/test_metadata_probe_queue.py tests/unit/app/services/test_metadata_retry_tracker.py tests/unit/app/services/test_media_metadata.py tests/integration/app/core/downloaders/test_runtime.py
git commit -m "fix: bound runtime metadata and ffmpeg diagnostics"
git push origin main
```

### Task 7: Transactional Playback Position Rows

**Files:**
- Modify: `app/services/playback_position_service.py`
- Modify: `tests/unit/app/services/test_playback_position.py`
- Modify: `tests/integration/app/services/test_runtime_state_concurrency.py`

**Interfaces:**
- Preserves `get`, `save`, `delete`, `clear`, `cleanup`, and `snapshot` public behavior.
- Keeps constructor `file_path`; a `.json` suffix is treated as a legacy import source and SQLite is stored beside it as `playback_positions.sqlite3`.
- Produces committed row mutations keyed by normalized path.

- [ ] **Step 1: Write two-writer, cleanup, and migration tests**

```python
def test_two_services_merge_distinct_positions(tmp_path):
    database = tmp_path / "playback_positions.sqlite3"
    first = PlaybackPositionService(file_path=database)
    second = PlaybackPositionService(file_path=database)
    first.save(tmp_path / "a.mp4", 1000)
    second.save(tmp_path / "b.mp4", 2000)
    snapshot = PlaybackPositionService(file_path=database).snapshot()
    assert set(snapshot) == {
        PlaybackPositionService.normalize_path(tmp_path / "a.mp4"),
        PlaybackPositionService.normalize_path(tmp_path / "b.mp4"),
    }

def test_cleanup_is_durable_before_return(tmp_path):
    service = PlaybackPositionService(file_path=tmp_path / "positions.sqlite3")
    missing = tmp_path / "missing.mp4"
    service.save(missing, 800)
    assert service.cleanup() == 1
    assert PlaybackPositionService(file_path=service.file_path).get(missing) == 0

def test_legacy_json_import_runs_once(tmp_path):
    legacy = write_legacy_positions(tmp_path, {"video.mp4": 900})
    first = PlaybackPositionService(file_path=legacy)
    assert first.get(tmp_path / "video.mp4") == 900
    legacy.write_text('{"entries": {}}', encoding="utf-8")
    second = PlaybackPositionService(file_path=legacy)
    assert second.get(tmp_path / "video.mp4") == 900
```

- [ ] **Step 2: Run playback tests and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_playback_position.py tests/integration/app/services/test_runtime_state_concurrency.py -q -k "merge_distinct or durable_before or import_runs_once"`

Expected: assertions fail because whole-file JSON writes lose concurrent updates and migration state does not exist.

- [ ] **Step 3: Write WAL row storage and one-time import marker**

```sql
CREATE TABLE playback_positions (
    normalized_path TEXT PRIMARY KEY,
    position_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    file_size INTEGER,
    file_mtime_ns INTEGER,
    updated_at REAL NOT NULL
);
CREATE TABLE playback_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Each mutation opens a short transaction with `busy_timeout = 5000`. `cleanup()` deletes and counts rows in one transaction. Import legacy JSON while holding `BEGIN IMMEDIATE`, skip when `legacy_json_imported=1`, upsert every valid entry, set the marker, commit, then rename the JSON to a unique `.migrated` sibling.

- [ ] **Step 4: Run playback, concurrency, taxonomy, and collection checks**

Run: `python -m pytest tests/unit/app/services/test_playback_position.py tests/integration/app/services/test_runtime_state_concurrency.py -q`

Expected: all tests pass.

Run: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q`

Expected: all tests pass.

Run: `python -m pytest tests --collect-only -q`

Expected: collection succeeds.

- [ ] **Step 5: Commit and push Task 7**

```bash
git add app/services/playback_position_service.py tests/unit/app/services/test_playback_position.py tests/integration/app/services/test_runtime_state_concurrency.py
git commit -m "fix: persist playback positions by transactional row"
git push origin main
```
