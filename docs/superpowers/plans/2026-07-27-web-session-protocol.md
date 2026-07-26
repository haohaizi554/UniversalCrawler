# Web Session Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver bootstrap and live Web state through one ordered writer per connection without event-loop blocking, delta gaps, stale-generation sends, or broken BFCache restoration.

**Architecture:** Each connection owns an outbox, generation, `last_written_version`, and at most one unwritten state payload. Enqueue does not advance versions: the sender advances `last_written_version` after `send_text()` returns successfully. New invalidations replace a queued payload by recomputing from `last_written_version` and current authoritative state; an in-flight payload records dirtiness and triggers a fresh recomputation after its write. Unsafe delta reconstruction falls back to a full snapshot.

**Tech Stack:** Python 3.10+, asyncio, FastAPI WebSocket, bounded queues, vanilla JavaScript, pytest, Playwright.

## Global Constraints

- Follow `tests/AGENTS.md`; protocol contracts live under `tests/contract/web/`, browser journeys under `tests/e2e/web/`, and isolated transport behavior under `tests/unit/app/web/`.
- `last_written_version` means bytes were successfully written by `WebSocket.send_text()`; accepted or queued messages do not advance it.
- One connection has one sender task; bootstrap, snapshots, deltas, action results, and legacy events enter the same outbox.
- A connection has at most one unwritten state payload across queued and in-flight states.
- While a state payload is unwritten, no chained delta is built from its target version.
- Queued coalescing recomputes a covering payload from `last_written_version` and current authoritative state. If history cannot cover that base, enqueue a full snapshot.
- An in-flight state payload is immutable; invalidations set `state_dirty`, and the sender schedules recomputation after the write succeeds.
- Send failure does not advance `last_written_version`; it closes that connection generation.
- A closed generation cannot enqueue, send, or mutate version state.
- `pagehide` suspends BFCache-capable resources; persisted `pageshow` reconnects and requests authoritative state.
- Stage and push each task with exact file paths.

---

## File Structure

- Modify `app/web/ws_transport.py`: connection generation, state-outbox slot, single sender, and write-confirmed version.
- Modify `app/web/controller.py`: invalidation scheduling without a global delivered version.
- Modify `app/web/ws_bootstrap.py`, `app/web/ws_router.py`, and `app/web/ws_runtime.py`: connect before bootstrap and generation-safe teardown.
- Modify `app/web/static/frontend_runtime.js`: BFCache suspend/restore state machine.
- Extend unit tests under `tests/unit/app/web/`.
- Create `tests/contract/web/test_frontend_runtime.py`; add the browser case to `tests/support/browser_cases/frontend_runtime.py` and its existing `tests/e2e/web/test_browser_journeys.py` assembly.

---

### Task 1: Single-Writer Covering State Outbox

**Files:**
- Modify: `app/web/ws_transport.py`
- Modify: `app/web/controller.py`
- Modify: `tests/unit/app/web/test_websocket_transport.py`
- Modify: `tests/unit/app/web/test_websocket_bridge.py`
- Create: `tests/contract/web/test_state_delivery_protocol.py`

**Interfaces:**
- Produces `WebSocketConnection(generation: int, last_written_version: int, state_payload: OutboundStatePayload | None, state_in_flight: bool, state_dirty: bool, state_build_task: asyncio.Task | None)`.
- Produces `OutboundStatePayload(kind: Literal["delta", "snapshot"], base_version: int, version: int, text: str, generation: int)`.
- Produces `ConnectionManager.invalidate_session_state(session_id: str, state_provider: Callable[[int], dict[str, Any]]) -> bool`.
- Produces provider result `{kind, base_version, version, state}` for snapshots or `{kind, base_version, version, changed_sections, sections}` for deltas.

- [ ] **Step 1: Write write-confirmation, covering-coalesce, and fallback tests**

```python
async def test_last_written_version_advances_after_send_returns():
    websocket = BlockingWebSocket()
    manager, connection = await connected_manager(websocket)
    await manager.invalidate_session_state("session", provider_for(delta_payload(0, 2)))
    await websocket.send_started.wait()
    assert connection.last_written_version == 0
    websocket.release_send.set()
    await wait_until(lambda: connection.last_written_version == 2)

async def test_queued_invalidation_recomputes_covering_delta_from_last_written():
    provider = RecordingProvider(authoritative_version=5)
    manager, connection = await connected_manager(PausedSenderWebSocket())
    await manager.invalidate_session_state("session", provider)
    provider.authoritative_version = 8
    await manager.invalidate_session_state("session", provider)
    assert provider.requested_bases == [0, 0]
    assert connection.state_payload.base_version == 0
    assert connection.state_payload.version == 8

async def test_in_flight_invalidation_does_not_build_delta_chain():
    provider = RecordingProvider(authoritative_version=4)
    websocket = BlockingWebSocket()
    manager, connection = await connected_manager(websocket)
    await manager.invalidate_session_state("session", provider)
    await websocket.send_started.wait()
    provider.authoritative_version = 7
    await manager.invalidate_session_state("session", provider)
    assert provider.requested_bases == [0]
    assert connection.state_dirty is True
    websocket.release_send.set()
    await wait_until(lambda: provider.requested_bases == [0, 4])

async def test_missing_history_replaces_delta_with_snapshot():
    manager, connection = await connected_manager(PausedSenderWebSocket())
    await manager.invalidate_session_state("session", provider_without_history(current_version=12))
    assert connection.state_payload.kind == "snapshot"
    assert connection.state_payload.version == 12
```

- [ ] **Step 2: Run focused transport/protocol tests and confirm RED**

Run: `python -m pytest tests/unit/app/web/test_websocket_transport.py tests/unit/app/web/test_websocket_bridge.py tests/contract/web/test_state_delivery_protocol.py -q -k "last_written or covering_delta or delta_chain or replaces_delta"`

Expected: assertions fail because enqueue acceptance advances global bridge state and coalescing does not preserve a per-connection base.

- [ ] **Step 3: Write the per-connection state slot and sender transition**

Invalidation holds `connection.queue_lock` long enough to mark `state_dirty` and schedule at most one `state_build_task`; it never calls the provider or JSON encoder on the event loop. The builder snapshots `last_written_version` and generation, invokes the provider and encoder in the executor, then reacquires the lock for this transition:

1. When `state_in_flight` is true, retain `state_dirty = True`, discard the speculative build, and let the sender schedule rebuilding after its write.
2. When a queued `state_payload` exists and generation/base still match, replace it with the recomputed covering delta or snapshot and keep one queue marker.
3. With no unwritten state payload and matching generation/base, enqueue one state marker.
4. When another invalidation arrived during building, repeat from the unchanged `last_written_version`; never use the queued payload's target version as a base.

The sender owns version advancement:

```python
await connection.ws.send_text(payload.text)
async with connection.queue_lock:
    if payload.generation != connection.generation or connection.closed:
        return
    connection.last_written_version = payload.version
    connection.state_in_flight = False
    should_recompute = connection.state_dirty
    connection.state_dirty = False
if should_recompute:
    await self.invalidate_connection_state(connection, provider)
```

On send exception, set `closed`, retain the old `last_written_version`, cancel that generation, and disconnect. Remove `_last_delta_version` and `mark_frontend_version_sent()` from `WebSocketBridge`; the bridge records authoritative invalidations and delegates per-connection recomputation to the manager.

- [ ] **Step 4: Run unit and protocol suites**

Run: `python -m pytest tests/unit/app/web/test_websocket_transport.py tests/unit/app/web/test_websocket_bridge.py tests/contract/web/test_state_delivery_protocol.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 1**

```bash
git add app/web/ws_transport.py app/web/controller.py tests/unit/app/web/test_websocket_transport.py tests/unit/app/web/test_websocket_bridge.py tests/contract/web/test_state_delivery_protocol.py
git commit -m "fix: recompute covering websocket state payloads"
git push origin main
```

### Task 2: Pre-Bootstrap Isolation, Ordered Activation, and Generation Shutdown

**Files:**
- Modify: `app/web/ws_bootstrap.py`
- Modify: `app/web/ws_router.py`
- Modify: `app/web/ws_runtime.py`
- Modify: `app/web/ws_transport.py`
- Modify: `app/web/controller.py`
- Modify: `tests/unit/app/web/test_websocket_bootstrap.py`
- Modify: `tests/unit/app/web/test_websocket_runtime.py`
- Modify: `tests/unit/app/web/test_websocket_transport.py`

**Interfaces:**
- Produces `ConnectionPhase` values `PRE_BOOTSTRAP`, `ACTIVE`, and `CLOSED`.
- Produces `ConnectionManager.prepare_connection(ws: WebSocket, session_id: str) -> WebSocketConnection`; prepared connections live in `_pre_bootstrap_connections`, not `active_connections`.
- Produces `enqueue_bootstrap_snapshot(connection: WebSocketConnection, snapshot: dict[str, Any]) -> BootstrapTicket` and `activate_connection(connection: WebSocketConnection, ticket: BootstrapTicket, state_provider: Callable[[int], dict[str, Any]]) -> bool`.
- Produces `send_to_connection(connection: WebSocketConnection, event_type: str, data: Any) -> bool`.
- Produces `close_generation(connection: WebSocketConnection) -> None`.

- [ ] **Step 1: Write bootstrap FIFO and stale-generation tests**

```python
async def test_pre_bootstrap_connection_is_not_active_or_broadcast_visible():
    connection = await manager.prepare_connection(websocket, "session")
    assert connection.phase is ConnectionPhase.PRE_BOOTSTRAP
    assert manager.active_connection_count() == 0
    assert await manager.emit_to_session("session", "task_started", {"video_id": "v"}) is False
    assert connection.outbound_queue == deque()

async def test_activation_barrier_orders_concurrent_live_event_after_snapshot():
    websocket = PausedSenderWebSocket()
    connection = await manager.prepare_connection(websocket, "session")
    ticket = await manager.enqueue_bootstrap_snapshot(connection, snapshot(version=3))
    lock_held = asyncio.Event()
    release_activation = asyncio.Event()
    manager.set_activation_test_barrier(lock_held, release_activation)
    activation = asyncio.create_task(manager.activate_connection(connection, ticket, provider))
    await lock_held.wait()
    broadcast = asyncio.create_task(
        manager.emit_to_session("session", "task_started", {"video_id": "v"})
    )
    await asyncio.sleep(0)
    assert broadcast.done() is False
    release_activation.set()
    assert await activation is True
    assert await broadcast is True
    websocket.release_send.set()
    await wait_until(lambda: len(websocket.messages) >= 2)
    assert message_types(websocket.messages)[:2] == ["frontend_state", "task_started"]

async def test_activation_schedules_catch_up_from_bootstrap_version():
    connection = await manager.prepare_connection(websocket, "session")
    ticket = await manager.enqueue_bootstrap_snapshot(connection, snapshot(version=3))
    provider = RecordingProvider(authoritative_version=5)
    assert await manager.activate_connection(connection, ticket, provider) is True
    await wait_until(lambda: provider.requested_bases == [3])

async def test_closed_generation_rejects_late_enqueue_and_version_write():
    old = await manager.prepare_connection(old_websocket, "session")
    manager.close_generation(old)
    new = await manager.prepare_connection(new_websocket, "session")
    assert await manager.send_to_connection(old, "frontend_delta", delta_payload(0, 3)) is False
    assert new.generation > old.generation
    assert old.last_written_version == 0
```

- [ ] **Step 2: Run focused bootstrap/runtime tests and confirm RED**

Run: `python -m pytest tests/unit/app/web/test_websocket_bootstrap.py tests/unit/app/web/test_websocket_runtime.py tests/unit/app/web/test_websocket_transport.py -q -k "pre_bootstrap or activation_barrier or activation_schedules or closed_generation"`

Expected: assertions fail because connection registration precedes bootstrap, broadcasts can observe it early, and delayed tasks survive connection replacement.

- [ ] **Step 3: Write connect-bootstrap-run-close ordering**

```python
binding = await binder.bind(websocket)
if binding is None:
    return
connection = await manager.prepare_connection(websocket, binding.session_id)
try:
    snapshot = await bootstrapper.build_snapshot(binding.context)
    ticket = await manager.enqueue_bootstrap_snapshot(connection, snapshot)
    activated = await manager.activate_connection(
        connection,
        ticket,
        binding.context.controller.get_frontend_delta,
    )
    if not activated:
        return
    binding.context.mark_websocket_connected()
    await runtime.run(connection, binding.context)
finally:
    manager.close_generation(connection)
    if connection.phase_was_active:
        binding.context.mark_websocket_disconnected()
```

`activate_connection()` acquires `_connections_lock` and `connection.queue_lock`, verifies the ticket belongs to the current generation and its snapshot is queued, in flight, or already written, removes the connection from `_pre_bootstrap_connections`, changes phase to `ACTIVE`, and inserts it into `active_connections` before releasing either lock. Broadcast takes `_connections_lock`, so a concurrent event observes no connection before activation or enqueues after the already-present snapshot. Activation marks state dirty from the snapshot version and schedules a covering catch-up payload from current authoritative state, closing the gap for events that occurred while pre-bootstrap. Snapshot creation and encoding run outside locks.

`close_generation()` removes the connection from its phase-specific registry, marks `CLOSED` under the queue lock, cancels sender/delta-builder/delayed-flush tasks for that generation, clears queue state, and prevents done callbacks from touching a replacement connection. Bootstrap failure closes the prepared generation without ever incrementing the context's active-WebSocket count.

- [ ] **Step 4: Run all WebSocket unit tests**

Run: `python -m pytest tests/unit/app/web/test_websocket_bootstrap.py tests/unit/app/web/test_websocket_runtime.py tests/unit/app/web/test_websocket_transport.py tests/unit/app/web/test_websocket_bridge.py tests/unit/app/web/test_websocket_session_binding.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit and push Task 2**

```bash
git add app/web/ws_bootstrap.py app/web/ws_router.py app/web/ws_runtime.py app/web/ws_transport.py app/web/controller.py tests/unit/app/web/test_websocket_bootstrap.py tests/unit/app/web/test_websocket_runtime.py tests/unit/app/web/test_websocket_transport.py
git commit -m "fix: serialize websocket bootstrap by generation"
git push origin main
```

### Task 3: BFCache Suspend and Restore

**Files:**
- Modify: `app/web/static/frontend_runtime.js`
- Create: `tests/contract/web/test_frontend_runtime.py`
- Modify: `tests/support/browser_cases/frontend_runtime.py`
- Modify: `tests/e2e/web/test_browser_journeys.py`

**Interfaces:**
- Produces frontend states `active`, `suspended`, and `disposed`.
- Produces `suspendPageResources()`, `restorePageResources(event)`, and `disposePageResources()`.

- [ ] **Step 1: Write contract and browser restoration tests**

```python
def test_frontend_registers_distinct_bfcache_suspend_and_restore_handlers():
    source = FRONTEND_RUNTIME.read_text(encoding="utf-8")
    def listener_target(event_name):
        pattern = rf'window\.addEventListener\(["\']{event_name}["\']\s*,\s*([A-Za-z0-9_]+)'
        match = re.search(pattern, source)
        return match.group(1) if match else None
    assert listener_target("pagehide") == "suspendPageResources"
    assert listener_target("pageshow") == "restorePageResources"
    assert listener_target("beforeunload") == "disposePageResources"

def test_persisted_pageshow_reconnects_and_fetches_authoritative_state(self):
    self._goto_ready()
    result = self._page.evaluate(
        """
        async () => {
          const runtime = window.UcpFrontendRuntime;
          runtime.dispose();
          const NativeWebSocket = window.WebSocket;
          const nativeFetch = window.fetch;
          const sockets = [];
          let fetches = 0;
          class FakeWebSocket {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSED = 3;
            constructor() { this.readyState = FakeWebSocket.OPEN; sockets.push(this); }
            close() { this.readyState = FakeWebSocket.CLOSED; }
            send() {}
          }
          window.WebSocket = FakeWebSocket;
          window.fetch = async () => {
            fetches += 1;
            return { ok: true, json: async () => ({ version: fetches }) };
          };
          try {
            await runtime.start();
            const socketsBeforeRestore = sockets.length;
            const fetchesBeforeRestore = fetches;
            window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
            window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
            await new Promise(resolve => setTimeout(resolve, 0));
            return {
              socketsBeforeRestore,
              socketsAfterRestore: sockets.length,
              fetchesBeforeRestore,
              fetchesAfterRestore: fetches,
            };
          } finally {
            runtime.dispose();
            window.WebSocket = NativeWebSocket;
            window.fetch = nativeFetch;
          }
        }
        """
    )
    self.assertEqual(result["socketsAfterRestore"], result["socketsBeforeRestore"] + 1)
    self.assertGreater(result["fetchesAfterRestore"], result["fetchesBeforeRestore"])
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/contract/web/test_frontend_runtime.py -q`

Expected: contract assertions fail because no persisted `pageshow` restoration exists.

Run: `python -m pytest tests/e2e/web/test_browser_journeys.py -q -m browser -k "persisted_pageshow"`

Expected: the browser test fails because pagehide performs irreversible cleanup.

- [ ] **Step 3: Write the frontend lifecycle state machine**

`pagehide` changes `active -> suspended`, clears reconnect timers, and closes the current socket without removing listeners. A persisted `pageshow` changes `suspended -> active`, opens one WebSocket, and calls the existing forced authoritative-state loader. `beforeunload` changes any state to `disposed`, removes listeners, and blocks later reconnect callbacks. Repeated events are idempotent.

```javascript
function restorePageResources(event) {
  if (!event.persisted || runtimeLifecycleState !== "suspended") return;
  runtimeLifecycleState = "active";
  connectWebSocket();
  void loadInitialState({ force: true });
}
```

- [ ] **Step 4: Run contract, browser, syntax, taxonomy, and collection checks**

Run: `node --check app/web/static/frontend_runtime.js`

Expected: exit code 0.

Run: `python -m pytest tests/contract/web/test_frontend_runtime.py -q`

Expected: all contract tests pass.

Run: `python -m pytest tests/e2e/web/test_browser_journeys.py -q -m browser -k "persisted_pageshow"`

Expected: all selected tests pass.

Run: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q`

Expected: all tests pass.

Run: `python -m pytest tests --collect-only -q`

Expected: collection succeeds.

- [ ] **Step 5: Commit and push Task 3**

```bash
git add app/web/static/frontend_runtime.js tests/contract/web/test_frontend_runtime.py tests/support/browser_cases/frontend_runtime.py tests/e2e/web/test_browser_journeys.py
git commit -m "fix: restore web sessions after bfcache navigation"
git push origin main
```
