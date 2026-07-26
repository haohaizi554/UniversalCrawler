# Download Recovery Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent one process or duplicate video task from overwriting or deleting another task's recovery state, and prevent resumed downloads from appending bytes from a changed resource.

**Architecture:** A process lease is authenticated by a random instance secret whose hash is persisted and by an operating-system process start token that detects PID reuse. Recovery rows use `task_run_id`, stale rows require an expired lease plus a second liveness check, and cleanup claims are expiring CAS-protected capabilities. HTTP partial files carry an atomic validator sidecar and append only after a matching `If-Range` response.

**Tech Stack:** Python 3.10+, SQLite/WAL, `secrets`, `hashlib`, Windows `GetProcessTimes`, Linux `/proc`, HTTP Range semantics, pytest.

## Global Constraints

- Keep Python 3.10 through 3.13 compatibility.
- Follow `tests/AGENTS.md`: unit tests mirror the production namespace; cross-process SQLite tests live under `tests/integration/`.
- Use `secrets.token_urlsafe(32)` for process and claim capabilities; persist SHA-256 token hashes, never plaintext tokens.
- Treat process-liveness `UNKNOWN` as live for deletion decisions, so uncertainty fails closed.
- A recovery row is cleanup-eligible after both its lease expires and PID/start-token liveness returns `DEAD` or `REUSED`.
- Claims have an expiry and can be reclaimed only after the claimant process instance is confirmed dead or reused; renew, completion, release, and late completion compare claim ID, claim-token hash, claimant lease identity, row generation, and observed expiry in one transaction.
- Use `task_run_id` as storage and cancellation identity; keep `video_id` as non-unique display metadata.
- Append a partial HTTP file after a matching strong ETag or Last-Modified `If-Range` exchange; otherwise restart at byte zero.
- Run taxonomy and collection checks after creating tests.
- Stage and push each task with the exact file list shown in that task.

---

## File Structure

- Create `app/services/process_lease.py`: OS process identity, authenticated lease handles, CAS acquire/renew/release, and fail-closed liveness.
- Modify `app/services/download_recovery_store.py`: `task_run_id` schema migration, lease-aware stale selection, expiring cleanup claims, and claim completion.
- Modify `app/core/download_manager_core.py`: lease heartbeat, task-run allocation, task-run cancellation, and startup claim orchestration.
- Modify `app/core/download_manager.py`: preserve task-run identity through worker callbacks and terminal recovery transitions.
- Create `app/core/downloaders/resume_state.py`: atomic validator sidecar and append decision.
- Modify `app/core/downloaders/base.py` and `app/core/downloaders/bilibili.py`: validator-bound resume and safe restart.
- Create `tests/unit/app/services/test_process_lease.py` and `tests/unit/app/core/downloaders/test_resume_state.py`.
- Modify `tests/unit/app/services/test_download_recovery_store.py` and `tests/unit/app/core/downloaders/test_manager_core.py`.
- Create `tests/integration/app/services/test_download_recovery_concurrency.py` and focused stream-resume tests under the downloader namespace.

---

### Task 1: Authenticated Process Identity and Lease CAS

**Files:**
- Create: `app/services/process_lease.py`
- Create: `tests/unit/app/services/test_process_lease.py`

**Interfaces:**
- Produces `ProcessIdentity(pid: int, start_token: str)`.
- Produces `LeaseHandle(owner_id: str, instance_token: str, lease_generation: str, pid: int, process_start_token: str, expires_at: float)`; `instance_token` exists in memory and is never returned by row-inspection APIs.
- Produces `ProcessLiveness` values `LIVE`, `DEAD`, `REUSED`, and `UNKNOWN`.
- Produces `ProcessIdentityProvider.current() -> ProcessIdentity` and `inspect(pid: int, expected_start_token: str) -> ProcessLiveness`.
- Produces `ProcessLeaseStore.acquire(owner_id: str | None = None) -> LeaseHandle`, `renew(handle: LeaseHandle) -> LeaseHandle | None`, `release(handle: LeaseHandle) -> bool`, and `is_cleanup_safe(owner_id: str, now: float | None = None) -> bool`.

- [ ] **Step 1: Write lease authentication and liveness tests**

```python
def test_forged_instance_token_cannot_renew_or_release(tmp_path):
    store = lease_store(tmp_path, liveness=ProcessLiveness.LIVE)
    handle = store.acquire(owner_id="desktop-a")
    forged = dataclasses.replace(handle, instance_token=secrets.token_urlsafe(32))
    assert store.renew(forged) is None
    assert store.release(forged) is False
    assert store.renew(handle) is not None

def test_stale_handle_cannot_overwrite_newer_renewal(tmp_path):
    store = lease_store(tmp_path, liveness=ProcessLiveness.LIVE)
    stale = store.acquire(owner_id="desktop-a")
    current = store.renew(stale)
    assert current is not None
    assert store.renew(stale) is None
    assert store.release(stale) is False
    assert store.release(current) is True

def test_expired_lease_is_not_cleanup_safe_when_process_is_still_live(tmp_path):
    clock = MutableClock(100.0)
    store = lease_store(tmp_path, clock=clock, liveness=ProcessLiveness.LIVE, ttl_seconds=5.0)
    store.acquire(owner_id="desktop-a")
    clock.value = 106.0
    assert store.is_cleanup_safe("desktop-a") is False

@pytest.mark.parametrize("liveness", [ProcessLiveness.DEAD, ProcessLiveness.REUSED])
def test_expired_lease_is_cleanup_safe_after_secondary_liveness_check(tmp_path, liveness):
    clock = MutableClock(100.0)
    store = lease_store(tmp_path, clock=clock, liveness=liveness, ttl_seconds=5.0)
    store.acquire(owner_id="desktop-a")
    clock.value = 106.0
    assert store.is_cleanup_safe("desktop-a") is True

def test_unknown_liveness_fails_closed(tmp_path):
    clock = MutableClock(100.0)
    store = lease_store(tmp_path, clock=clock, liveness=ProcessLiveness.UNKNOWN, ttl_seconds=5.0)
    store.acquire(owner_id="desktop-a")
    clock.value = 106.0
    assert store.is_cleanup_safe("desktop-a") is False
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_process_lease.py -q`

Expected: collection fails because `app.services.process_lease` does not exist.

- [ ] **Step 3: Write the OS identity provider and authenticated lease store**

```python
@dataclass(frozen=True)
class LeaseHandle:
    owner_id: str
    instance_token: str = field(repr=False)
    lease_generation: str
    pid: int
    process_start_token: str
    expires_at: float

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def renew(self, handle: LeaseHandle) -> LeaseHandle | None:
    now = float(self._clock())
    expires_at = now + self._ttl_seconds
    with closing(self._connect()) as conn, conn:
        cursor = conn.execute(
            """
            UPDATE process_leases
            SET heartbeat_at = ?, expires_at = ?
            WHERE owner_id = ? AND instance_token_hash = ?
              AND lease_generation = ? AND pid = ?
              AND process_start_token = ? AND expires_at = ?
            """,
            (
                now,
                expires_at,
                handle.owner_id,
                _token_hash(handle.instance_token),
                handle.lease_generation,
                handle.pid,
                handle.process_start_token,
                handle.expires_at,
            ),
        )
    if int(cursor.rowcount or 0) != 1:
        return None
    return dataclasses.replace(handle, expires_at=expires_at)
```

`process_leases` stores `owner_id`, `instance_token_hash`, `lease_generation`, PID, process start token, heartbeat, and expiry. `acquire()` generates a new instance token and generation, begins `BEGIN IMMEDIATE`, and inserts with `ON CONFLICT DO NOTHING`. For an existing owner, it records the observed hash/generation/expiry, confirms `expires_at < now` and liveness `DEAD` or `REUSED`, then updates with a `WHERE` clause matching all observed values. `renew()` and `release()` match token hash, generation, PID, start token, and the handle's observed expiry, so stale handles fail CAS. On Windows, obtain creation FILETIME through `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` and `GetProcessTimes`; on Linux, use boot ID plus `/proc/<pid>/stat` field 22. Permission, parsing, and unsupported-platform failures return `UNKNOWN`.

- [ ] **Step 4: Run the lease test and static checks**

Run: `python -m pytest tests/unit/app/services/test_process_lease.py -q`

Expected: all tests pass.

Run: `python -m ruff check app/services/process_lease.py tests/unit/app/services/test_process_lease.py`

Expected: exit code 0.

- [ ] **Step 5: Commit and push Task 1**

```bash
git add app/services/process_lease.py tests/unit/app/services/test_process_lease.py
git commit -m "feat: authenticate process recovery leases"
git push origin main
```

### Task 2: Task-Run Schema and Reclaimable Cleanup Claims

**Files:**
- Modify: `app/services/download_recovery_store.py`
- Modify: `tests/unit/app/services/test_download_recovery_store.py`
- Create: `tests/integration/app/services/test_download_recovery_concurrency.py`

**Interfaces:**
- Consumes `ProcessLeaseStore.is_cleanup_safe()` from Task 1.
- Produces `RecoveryTask(task_run_id: str, video_id: str, owner_id: str, save_directory: str, generation: str)`.
- Produces `RecoveryClaim(claim_id: str, claim_token: str, claimant_owner_id: str, claimant_lease_generation: str, claimant_pid: int, claimant_process_start_token: str, expires_at: float, tasks: Sequence[RecoveryTask])`.
- Produces `register_task(task_run_id: str, owner_id: str, video_id: str, save_directory: str, source_url: str = "", trace_id: str = "", platform: str = "") -> None`.
- Produces `claim_stale_recovery(claimant: LeaseHandle, ttl_seconds: float = 60.0) -> RecoveryClaim` and `renew_claim(claim: RecoveryClaim, claimant: LeaseHandle, ttl_seconds: float = 60.0) -> RecoveryClaim | None`.
- Produces `validate_cleanup_target(claim: RecoveryClaim, claimant: LeaseHandle, task_run_id: str, candidate_path: Path) -> bool`.
- Produces `complete_claim(claim: RecoveryClaim, claimant: LeaseHandle, committed_task_run_ids: Sequence[str], quarantine_root: Path) -> CleanupCommitReceipt | None` and `release_claim(claim: RecoveryClaim, claimant: LeaseHandle, task_run_ids: Sequence[str]) -> int`.
- Produces `validate_committed_target(receipt: CleanupCommitReceipt, candidate_path: Path) -> bool` and `finish_cleanup_commit(receipt: CleanupCommitReceipt) -> bool` for post-commit quarantine deletion.

- [ ] **Step 1: Write duplicate-ID, claim-CAS, and claim-expiry tests**

```python
def test_duplicate_video_ids_keep_independent_rows(store, live_handle, tmp_path):
    store.register_task("run-a", live_handle.owner_id, "same-video", str(tmp_path / "a"))
    store.register_task("run-b", live_handle.owner_id, "same-video", str(tmp_path / "b"))
    assert store.task_path("run-a")["video_id"] == "same-video"
    assert store.task_path("run-b")["video_id"] == "same-video"
    assert store.delete_task("run-a") is True
    assert store.task_path("run-b")["save_directory"].endswith("b")

def test_forged_claim_token_cannot_complete_cleanup(store, stale_task, claimant, quarantine_root):
    claim = store.claim_stale_recovery(claimant, ttl_seconds=30.0)
    forged = dataclasses.replace(claim, claim_token=secrets.token_urlsafe(32))
    assert store.complete_claim(forged, claimant, [stale_task.task_run_id], quarantine_root) is None
    assert store.task_path(stale_task.task_run_id) is not None

def test_expired_claim_can_be_reclaimed_after_cleaner_death(store, stale_task, first_claimant, second_claimant, clock, liveness):
    first = store.claim_stale_recovery(first_claimant, ttl_seconds=5.0)
    assert [task.task_run_id for task in first.tasks] == [stale_task.task_run_id]
    clock.value += 6.0
    liveness.set(first.claimant_pid, first.claimant_process_start_token, ProcessLiveness.DEAD)
    second = store.claim_stale_recovery(second_claimant, ttl_seconds=5.0)
    assert [task.task_run_id for task in second.tasks] == [stale_task.task_run_id]
    assert second.claim_id != first.claim_id

def test_expired_claim_cannot_be_reclaimed_while_prior_claimant_process_is_live(store, stale_task, first_claimant, second_claimant, clock, liveness):
    first = store.claim_stale_recovery(first_claimant, ttl_seconds=5.0)
    clock.value += 6.0
    liveness.set(first.claimant_pid, first.claimant_process_start_token, ProcessLiveness.LIVE)
    assert store.claim_stale_recovery(second_claimant, ttl_seconds=5.0).tasks == ()

def test_claim_renewal_uses_owner_instance_and_expiry_cas(store, stale_task, claimant):
    claim = store.claim_stale_recovery(claimant, ttl_seconds=5.0)
    forged_owner = dataclasses.replace(claimant, instance_token=secrets.token_urlsafe(32))
    assert store.renew_claim(claim, forged_owner, ttl_seconds=5.0) is None
    renewed = store.renew_claim(claim, claimant, ttl_seconds=5.0)
    assert renewed is not None
    assert renewed.expires_at > claim.expires_at
    assert store.renew_claim(claim, claimant, ttl_seconds=5.0) is None

def test_current_live_claimant_can_late_complete_unchanged_claim(store, stale_task, claimant, clock, quarantine_root):
    claim = store.claim_stale_recovery(claimant, ttl_seconds=5.0)
    clock.value += 6.0
    receipt = store.complete_claim(
        claim,
        claimant,
        [stale_task.task_run_id],
        quarantine_root,
    )
    assert receipt is not None
    assert store.task_path(stale_task.task_run_id) is None

def test_cleanup_validation_rejects_path_inside_current_active_root(store, claim, claimant, active_task):
    candidate = Path(active_task.save_directory) / "video.mp4.downloading"
    assert store.validate_cleanup_target(claim, claimant, claim.tasks[0].task_run_id, candidate) is False
```

The integration test opens two store instances against one database, starts claims concurrently at a barrier, and asserts exactly one live claim owns each row before its TTL.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/app/services/test_download_recovery_store.py tests/integration/app/services/test_download_recovery_concurrency.py -q -k "duplicate_video_ids or forged_claim or expired_claim or prior_claimant or claim_renewal or late_complete or active_root or concurrent_claim"`

Expected: tests fail because the current table uses `video_id` as its primary key and has no authenticated expiring claim.

- [ ] **Step 3: Migrate rows and write transactional claim operations**

```sql
CREATE TABLE download_task_paths_v2 (
    task_run_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    save_directory TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    updated_at REAL NOT NULL,
    generation TEXT NOT NULL,
    claim_id TEXT,
    claim_token_hash TEXT,
    claimed_by TEXT,
    claimant_instance_token_hash TEXT,
    claimant_lease_generation TEXT,
    claimant_pid INTEGER,
    claimant_process_start_token TEXT,
    claim_expires_at REAL
);
CREATE INDEX idx_download_task_paths_video_id ON download_task_paths_v2(video_id);
CREATE INDEX idx_download_task_paths_owner_state ON download_task_paths_v2(owner_id, state, updated_at);
```

Migrate legacy rows to generated `legacy-<uuid>` task-run IDs inside one transaction. `claim_stale_recovery()` uses `BEGIN IMMEDIATE`, verifies the new claimant lease handle by token-hash/generation/PID/start-token CAS, and selects source rows whose task owner is cleanup-safe. A row with an expired prior claim is reclaimable after the prior claim's stored PID/start token returns `DEAD` or `REUSED` and its stored process-lease instance is no longer current; TTL alone never authorizes reclaim. `UNKNOWN` and `LIVE` block reclaim.

Claim creation stores a claim-token hash plus claimant instance-token hash, lease generation, PID, process start token, and observed expiry on every claimed row. `renew_claim()` updates every row in one transaction with predicates for claim ID/token hash, row generation, claimant owner/instance hash/lease generation/PID/start token, and old claim expiry; a partial row count rolls back the renewal.

`validate_cleanup_target()` re-verifies the current unexpired claim and claimant lease, exact row generation, candidate containment under that row's save directory, and a fresh database snapshot of active roots. It rejects a candidate equal to, containing, or contained by a root currently owned by a live or liveness-unknown task.

`complete_claim()` accepts a just-expired claim from its still-current live claimant because reclaim is prohibited while that PID/start token is live. It atomically deletes rows whose claim ID/token, claimant instance, row generation, and committed task-run IDs remain unchanged, then inserts a `completed_cleanup_claims` receipt containing a random commit-token hash, the claim/row generations, and normalized quarantine root. This late-commit rule prevents a completed quarantine move from leaving records that a later cleaner could claim again. A changed claim or claimant lease rolls back the transaction. `release_claim()` clears unchanged uncommitted rows by the same CAS. `validate_committed_target()` requires the receipt token, quarantine containment, and a fresh non-overlap check against current active roots before each irreversible deletion; `finish_cleanup_commit()` removes the receipt by commit-token CAS after the quarantine is empty.

The normal completion predicate includes:

```sql
DELETE FROM download_task_paths
WHERE task_run_id = ? AND generation = ? AND claim_id = ?
  AND claim_token_hash = ? AND claimant_instance_token_hash = ?
  AND claimant_lease_generation = ?;
```

- [ ] **Step 4: Run recovery store and concurrency tests**

Run: `python -m pytest tests/unit/app/services/test_download_recovery_store.py tests/integration/app/services/test_download_recovery_concurrency.py -q`

Expected: all tests pass; `UNKNOWN` and `LIVE` owners never enter a claim.

- [ ] **Step 5: Commit and push Task 2**

```bash
git add app/services/download_recovery_store.py tests/unit/app/services/test_download_recovery_store.py tests/integration/app/services/test_download_recovery_concurrency.py
git commit -m "fix: isolate and claim stale recovery runs"
git push origin main
```

### Task 3: Download Manager Lease Heartbeat and Claimed Startup Cleanup

**Files:**
- Modify: `app/core/download_manager_core.py`
- Modify: `app/core/download_manager.py`
- Modify: `tests/unit/app/core/downloaders/test_manager_core.py`
- Modify: `tests/integration/app/services/test_download_recovery_concurrency.py`

**Interfaces:**
- Consumes `LeaseHandle`, `RecoveryClaim`, and task-run recovery APIs from Tasks 1-2.
- Produces `queued_task_run_ids() -> Sequence[str]` and `cancel_task_run(task_run_id: str, timeout_ms: int | None = None) -> str | None`.
- Produces a heartbeat loop that swaps in the renewed immutable `LeaseHandle`; a failed renew transitions the manager to reject-new-work mode.
- Produces `ClaimHeartbeat.current() -> RecoveryClaim | None`; it renews by claimant instance-token/lease-generation CAS every `claim_ttl / 3` and publishes the renewed immutable claim under a lock.
- Produces `CleanupJournal.quarantine(task_run_id: str, source: Path) -> Path`, `rollback() -> None`, and `purge(receipt: CleanupCommitReceipt) -> None`; quarantine paths are unique siblings on the same volume.

- [ ] **Step 1: Write manager identity and live-process cleanup tests**

```python
def test_cancelling_one_duplicate_video_run_keeps_the_other(manager, duplicate_video_items):
    first, second = duplicate_video_items
    manager.add_tasks([first, second], "downloads")
    first_run, second_run = manager.queued_task_run_ids()
    assert manager.cancel_task_run(first_run) is None
    assert manager.queued_task_run_ids() == (second_run,)

def test_failed_lease_renew_stops_new_admission(manager):
    manager._lease_store.renew.return_value = None
    manager._renew_process_lease()
    with pytest.raises(RuntimeError, match="recovery lease lost"):
        manager.add_task(video_item("new"), "downloads")

def test_second_manager_does_not_clean_live_first_manager_workspace(shared_database, tmp_path):
    first = manager_for(shared_database, owner_id="first")
    first.add_task(video_item("v"), str(tmp_path))
    partial = tmp_path / "v.mp4.downloading"
    partial.write_bytes(b"live")
    manager_for(shared_database, owner_id="second")
    assert partial.read_bytes() == b"live"

def test_slow_cleanup_renews_claim_with_current_owner_instance(manager, stale_workspace, clock):
    manager.startup_cleanup_barrier.block_after_first_quarantine()
    cleanup = manager.start_startup_cleanup()
    first_expiry = manager.current_recovery_claim.expires_at
    clock.value += manager.claim_ttl / 3
    manager.claim_heartbeat.tick()
    assert manager.current_recovery_claim.expires_at > first_expiry
    assert manager.recovery_store.last_renewal.claimant_instance_token_hash == token_hash(
        manager.lease_handle.instance_token
    )
    manager.startup_cleanup_barrier.release()
    cleanup.join()

def test_lost_claim_stops_cleaner_and_rolls_back_quarantine(first_manager, second_manager, stale_workspace, clock, liveness):
    first_manager.startup_cleanup_barrier.block_after_first_quarantine()
    cleanup = first_manager.start_startup_cleanup()
    quarantined = first_manager.cleanup_journal.moves[0]
    clock.value += first_manager.claim_ttl + 1
    liveness.set(
        first_manager.lease_handle.pid,
        first_manager.lease_handle.process_start_token,
        ProcessLiveness.REUSED,
    )
    replacement = second_manager.recovery_store.claim_stale_recovery(second_manager.lease_handle)
    assert replacement.tasks
    first_manager.startup_cleanup_barrier.release()
    cleanup.join()
    assert quarantined.source.exists()
    assert quarantined.quarantine.exists() is False
    assert first_manager.cleanup_journal.irreversible_delete_count == 0

def test_every_cleanup_target_rechecks_claim_generation_and_active_roots(manager, claimed_targets):
    manager.run_claimed_cleanup(claimed_targets)
    assert manager.recovery_store.validation_calls == [
        (target.task_run_id, target.row_generation, target.path)
        for target in claimed_targets
    ]
```

- [ ] **Step 2: Run manager and integration tests and confirm RED**

Run: `python -m pytest tests/unit/app/core/downloaders/test_manager_core.py tests/integration/app/services/test_download_recovery_concurrency.py -q -k "duplicate_video_run or lease_renew or live_first_manager or slow_cleanup or lost_claim or every_cleanup_target"`

Expected: tests fail because task operations and startup cleanup are keyed by `video_id` and do not hold an authenticated lease.

- [ ] **Step 3: Wire the lease and claim lifecycle into the manager**

Allocate `task_run_id = uuid.uuid4().hex` at queue admission, attach it to the queued entry and worker, and pass it to recovery registration, failure handoff, success deletion, cancellation, and callback lookup. Acquire the process lease before startup maintenance. Renew at `ttl_seconds / 3`; after renewal failure, reject new tasks and keep existing rows protected until their original lease expires and liveness confirms process death.

Startup cleanup follows this exact order:

```python
claim = self._recovery_store.claim_stale_recovery(self._lease_handle)
heartbeat = ClaimHeartbeat(self._recovery_store, claim, self._lease_handle, claim_ttl / 3)
journal = CleanupJournal.for_claim(claim)
heartbeat.start()
try:
    for task, target in self._claimed_cleanup_targets(claim.tasks):
        current = heartbeat.current()
        if current is None:
            raise ClaimLostError(current_claim_id=claim.claim_id)
        renewed = self._recovery_store.renew_claim(current, self._lease_handle, claim_ttl)
        if renewed is None:
            raise ClaimLostError(current_claim_id=claim.claim_id)
        heartbeat.replace(renewed)
        if not self._recovery_store.validate_cleanup_target(
            renewed,
            self._lease_handle,
            task.task_run_id,
            target,
        ):
            raise ClaimLostError(current_claim_id=claim.claim_id)
        journal.quarantine(task.task_run_id, target)
    final_claim = heartbeat.current()
    if final_claim is None:
        raise ClaimLostError(current_claim_id=claim.claim_id)
    receipt = self._recovery_store.complete_claim(
        final_claim,
        self._lease_handle,
        journal.task_run_ids,
        journal.root,
    )
    if receipt is None:
        raise ClaimLostError(current_claim_id=claim.claim_id)
    journal.purge(receipt)
    self._recovery_store.finish_cleanup_commit(receipt)
except ClaimLostError:
    journal.rollback()
    raise
finally:
    heartbeat.stop()
```

Before every original-path mutation, renew and validate claim token, claimant instance/lease generation, task row generation, expiry, containment, and current active roots. Original `.downloading` files and HLS workspaces are atomically renamed into a claim-scoped same-volume quarantine; no original is irreversibly deleted while the claim can expire. If heartbeat renewal, target validation, or completion CAS fails, stop immediately and roll back every journaled rename whose original path is still free. After successful completion removes recovery rows and creates a commit receipt, `purge()` validates that receipt and current active-root non-overlap before each quarantine deletion. A slow stale cleaner therefore cannot race a replacement claimant or leave a row eligible for duplicate deletion.

- [ ] **Step 4: Run manager, recovery, taxonomy, and collection checks**

Run: `python -m pytest tests/unit/app/core/downloaders/test_manager_core.py tests/unit/app/services/test_download_recovery_store.py tests/integration/app/services/test_download_recovery_concurrency.py -q`

Expected: all tests pass.

Run: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q`

Expected: all tests pass.

Run: `python -m pytest tests --collect-only -q`

Expected: collection succeeds.

- [ ] **Step 5: Commit and push Task 3**

```bash
git add app/core/download_manager_core.py app/core/download_manager.py tests/unit/app/core/downloaders/test_manager_core.py tests/integration/app/services/test_download_recovery_concurrency.py
git commit -m "fix: bind startup recovery to process leases"
git push origin main
```

### Task 4: Validator-Bound Stream Resume

**Files:**
- Create: `app/core/downloaders/resume_state.py`
- Modify: `app/core/downloaders/base.py`
- Modify: `app/core/downloaders/bilibili.py`
- Create: `tests/unit/app/core/downloaders/test_resume_state.py`
- Create: `tests/integration/app/core/downloaders/test_stream_resume.py`
- Create: `tests/integration/app/core/downloaders/bilibili/test_stream_resume.py`

**Interfaces:**
- Produces `ResumeState(url: str, strong_etag: str | None, last_modified: str | None, expected_length: int | None)`.
- Produces `load_resume_state(partial_path: Path) -> ResumeState | None`, `save_resume_state(partial_path: Path, state: ResumeState) -> None`, `remove_resume_state(partial_path: Path) -> None`, and `can_append(response: Any, state: ResumeState, offset: int) -> bool`.

- [ ] **Step 1: Write validator parsing and changed-resource tests**

```python
def test_weak_etag_is_not_a_strong_validator():
    state = ResumeState.from_headers("https://cdn.example/video", {"ETag": 'W/"v1"'})
    assert state.strong_etag is None

def test_matching_if_range_response_appends(local_http_server, tmp_path):
    server = local_http_server(body=b"abcdefgh", etag='"v1"', honor_range=True)
    partial = tmp_path / "video.mp4.downloading"
    partial.write_bytes(b"abcd")
    save_resume_state(partial, ResumeState(server.url, '"v1"', None, 8))
    download_to(server.url, tmp_path / "video.mp4", support_resume=True)
    assert server.requests[0].headers["Range"] == "bytes=4-"
    assert server.requests[0].headers["If-Range"] == '"v1"'
    assert (tmp_path / "video.mp4").read_bytes() == b"abcdefgh"

def test_changed_validator_restarts_without_old_prefix(local_http_server, tmp_path):
    server = local_http_server(body=b"NEW-CONTENT", etag='"v2"', honor_range=False)
    partial = tmp_path / "video.mp4.downloading"
    partial.write_bytes(b"OLD-")
    save_resume_state(partial, ResumeState(server.url, '"v1"', None, 11))
    download_to(server.url, tmp_path / "video.mp4", support_resume=True)
    assert (tmp_path / "video.mp4").read_bytes() == b"NEW-CONTENT"
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/unit/app/core/downloaders/test_resume_state.py tests/integration/app/core/downloaders/test_stream_resume.py tests/integration/app/core/downloaders/bilibili/test_stream_resume.py -q`

Expected: collection or assertions fail because ordinary and Bilibili streams do not persist and validate source identity.

- [ ] **Step 3: Write atomic sidecars and strict append decisions**

Persist `<partial>.resume.json` through a unique sibling temporary file, `flush()`, `os.fsync()`, and `os.replace()`. Send `Range` with `If-Range` from a strong ETag, falling back to Last-Modified. `can_append()` returns true when status is 206, `Content-Range` starts at the local offset, the URL matches, and the returned validator is consistent. A missing validator, status 200, mismatched range, changed validator, or malformed sidecar truncates the partial and retries once from byte zero. Remove the sidecar after successful publish and final failure cleanup.

Apply the same helper to Bilibili audio and video partial streams; each stream owns its own sidecar.

- [ ] **Step 4: Run downloader tests and static checks**

Run: `python -m pytest tests/unit/app/core/downloaders/test_resume_state.py tests/integration/app/core/downloaders/test_stream_resume.py tests/integration/app/core/downloaders/bilibili/test_stream_resume.py tests/unit/app/core/downloaders/bilibili/test_merge_process.py -q`

Expected: all tests pass.

Run: `python -m ruff check app/core/downloaders/resume_state.py app/core/downloaders/base.py app/core/downloaders/bilibili.py tests/unit/app/core/downloaders/test_resume_state.py tests/integration/app/core/downloaders/test_stream_resume.py tests/integration/app/core/downloaders/bilibili/test_stream_resume.py`

Expected: exit code 0.

- [ ] **Step 5: Commit and push Task 4**

```bash
git add app/core/downloaders/resume_state.py app/core/downloaders/base.py app/core/downloaders/bilibili.py tests/unit/app/core/downloaders/test_resume_state.py tests/integration/app/core/downloaders/test_stream_resume.py tests/integration/app/core/downloaders/bilibili/test_stream_resume.py
git commit -m "fix: bind partial downloads to source validators"
git push origin main
```
