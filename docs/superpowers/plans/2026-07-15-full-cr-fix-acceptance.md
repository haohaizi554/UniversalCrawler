# Full CR Fix Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every finding from the 2026-07-15 full-project code review, repair any remaining defect in the current local worktree, and prove the resulting tree against the required CI suites.

**Architecture:** Keep the user's existing dirty `main` worktree as the single source of truth. Parallel agents perform read-only subsystem reviews; the primary agent alone adds regression tests or production changes. Any discovered defect follows red-green TDD, while already-correct fixes are accepted through focused behavior tests and source-boundary inspection.

**Tech Stack:** Python 3.10-3.13, pytest/unittest, FastAPI, PyQt6, Playwright/Chromium, JavaScript Web Workers, Docker Buildx, setuptools wheels.

## Global Constraints

- Work directly in `D:/desktop/project/UniversalCrawlerProplus`; do not create an external worktree or clone.
- Preserve all existing user changes, including untracked tests and assets.
- Do not stage, commit, push, or rewrite history unless the user separately requests it.
- Use `apply_patch` for source edits.
- For every remaining defect, first add or identify a regression test that fails for the expected reason, then make the smallest production change that turns it green.
- Final completion requires fresh static checks, focused regression suites, required CI-equivalent suites, and a final diff review.

---

### Task 1: Security boundary acceptance

**Files:**
- Inspect: `app/core/downloaders/{m3u8,ffmpeg,hls_proxy}.py`
- Inspect: `shared/runtime_options.py`
- Inspect: `app/spiders/{base,missav/spider}.py`
- Inspect: `app/web/{http_session,session_runtime}.py`
- Test: `tests/test_downloaders.py`
- Test: `tests/test_spider_base.py`
- Test: `tests/test_fastapi_endpoints.py`
- Test: `tests/test_web_security_hardening.py`

**Interfaces:**
- Consumes: `VideoItem.meta["_network_policy"] == "public"`, `DomainPolicyEngine`, `HttpSessionCoordinator.handle()`.
- Produces: external-tool URLs constrained to a validating loopback proxy, browser requests checked per request, and stateless public ping responses.

- [ ] **Step 1: Verify external-tool public-network tests**

  Run:

  ```powershell
  python -m pytest tests/test_downloaders.py -q -p no:cacheprovider -k "public_external_hls or public_hls_download or public_yt_dlp or public_ffmpeg"
  ```

  Expected: the command builders receive only a validating loopback URL; no public-policy path receives the upstream URL directly.

- [ ] **Step 2: Verify Playwright redirect/subresource policy tests**

  Run:

  ```powershell
  python -m pytest tests/test_spider_base.py -q -p no:cacheprovider -k "playwright and (private or route or worker)"
  ```

  Expected: private requests are aborted and service workers cannot bypass routing.

- [ ] **Step 3: Verify public ping does not allocate a session**

  Run:

  ```powershell
  python -m pytest tests/test_fastapi_endpoints.py::PingEndpointTests::test_ping_without_cookies_does_not_allocate_sessions tests/test_web_security_hardening.py -q -p no:cacheprovider
  ```

  Expected: repeated cookie-less `/api/ping` calls leave the registry context count unchanged.

- [ ] **Step 4: Repair any failing security behavior with red-green TDD**

  Add the smallest failing assertion to the owning test above, rerun it to observe the intended failure, patch only the failing boundary, and rerun the same test to green.

---

### Task 2: Configuration and download-publish race acceptance

**Files:**
- Inspect: `app/config/settings.py`
- Inspect: `app/core/download_manager_core.py`
- Inspect: `app/core/downloaders/chunked.py`
- Inspect: `app/services/media_library_runtime.py`
- Test: `tests/test_config_settings.py`
- Test: `tests/test_download_publish_races.py`

**Interfaces:**
- Consumes: `ConfigManager._exclusive_file_lock()`, `start_external_sync()`, `stop_external_sync()`, `DownloadManager.cancel_task()`.
- Produces: coherent config rollback/signature state, per-watcher stop events, closed failed lock descriptors, and cancel-before-delete publication ordering.

- [ ] **Step 1: Verify config rollback, lock cleanup, and watcher restart tests**

  Run:

  ```powershell
  python -m pytest tests/test_config_settings.py -q -p no:cacheprovider
  ```

  Expected: injected metadata-write failure removes the lock, stale-manager failures preserve the refreshed disk state, and a timed-out watcher cannot revive after restart.

- [ ] **Step 2: Verify running-download deletion ordering**

  Run:

  ```powershell
  python -m pytest tests/test_download_publish_races.py -q -p no:cacheprovider
  ```

  Expected: delete waits for release before touching files and returns an explicit non-success outcome when release times out.

- [ ] **Step 3: Repair any failing lifecycle behavior with red-green TDD**

  Keep the reproduction in the focused test file, observe it fail, then patch the owning synchronization boundary without increasing global timeouts.

---

### Task 3: UI worker, identity, close, and modal-state acceptance

**Files:**
- Inspect: `app/web/static/{list_pages,log_display,log_center,app}.js`
- Inspect: `app/services/{app_state,frontend_log_cache,frontend_log_adapter}.py`
- Inspect: `app/ui/{main_window,window_state_persistence}.py`
- Test: `tests/test_log_row_ids.py`
- Test: `tests/test_main_window.py`
- Test: `tests/test_web_browser.py`

**Interfaces:**
- Consumes: worker error callbacks, backend log row IDs, window-state persistence worker, update-modal status.
- Produces: worker fallback after terminal failure, immutable log IDs across ring eviction, non-blocking close persistence, and Escape behavior consistent with disabled modal controls.

- [ ] **Step 1: Verify backend and worker-clone log ID stability**

  Run:

  ```powershell
  python -m pytest tests/test_log_row_ids.py tests/test_frontend_log_adapter.py -q -p no:cacheprovider
  ```

  Expected: duplicate rows retain immutable IDs when older rows are evicted and when objects cross worker cloning boundaries.

- [ ] **Step 2: Verify close-state persistence is off the GUI thread**

  Run:

  ```powershell
  python -m pytest tests/test_main_window.py -q -p no:cacheprovider -k "close or window_state"
  ```

  Expected: `closeEvent()` submits a snapshot without waiting on the three-second config lock.

- [ ] **Step 3: Verify list-worker recovery and update-modal Escape behavior**

  Run:

  ```powershell
  python -m pytest tests/test_web_browser.py -q -p no:cacheprovider -k "worker or escape or update"
  ```

  Expected: terminal worker errors schedule future fallbacks, and Escape cannot dismiss the installing handoff state.

- [ ] **Step 4: Repair any failing UI state transition with red-green TDD**

  Add a behavior-level assertion rather than an exact JavaScript-signature string assertion, observe the failure, patch the smallest state transition, and rerun the focused browser test.

---

### Task 4: Packaging, runtime paths, CLI, and CI-gate acceptance

**Files:**
- Inspect: `Dockerfile`
- Inspect: `.github/workflows/docker-build.yml`
- Inspect: `app/utils/runtime_paths.py`
- Inspect: `app/services/auth_service.py`
- Inspect: `app/web/server.py`
- Inspect: `entry/dispatcher.py`
- Inspect: `pyproject.toml`
- Test: `tests/test_{auth_service,ci_workflow,main_entry,packaging,runtime_paths}.py`
- Test: `tests/architecture/test_file_size_limits.py`
- Test: `tests/test_large_frontend_file_boundaries.py`

**Interfaces:**
- Consumes: wheel package data, runtime checkout detection, JSON credential persistence, dispatcher mode parsing, Docker build context.
- Produces: runnable Docker image, packaged favicon, per-user wheel state, atomic cookie writes, exit code 2 for invalid explicit mode, and modules below hard size ceilings.

- [ ] **Step 1: Verify focused packaging and CLI tests**

  Run:

  ```powershell
  python -m pytest tests/test_auth_service.py tests/test_ci_workflow.py tests/test_main_entry.py tests/test_packaging.py tests/test_runtime_paths.py -q -p no:cacheprovider
  ```

  Expected: cookie failure preserves the old file, installed-wheel runtime avoids `site-packages/user_data`, favicon package data is declared, invalid/missing mode returns 2, and Docker CI contains a startup smoke test.

- [ ] **Step 2: Verify architecture budgets and browser contract parsing**

  Run:

  ```powershell
  python -m pytest tests/architecture tests/test_large_frontend_file_boundaries.py tests/test_web_browser.py -q -p no:cacheprovider
  ```

  Expected: production and browser-case modules remain below enforced limits, and tests do not depend on an exact parameterless JavaScript signature.

- [ ] **Step 3: Validate Docker configuration without mutating the repository**

  Run when Docker is available:

  ```powershell
  docker compose -f docker-compose.yml config
  ```

  Expected: exit code 0. Inspect the workflow to confirm the built image is loaded, started, polled at `/healthz`, and removed.

- [ ] **Step 4: Repair any packaging or entrypoint gap with red-green TDD**

  Add the regression to the focused test file, observe it fail, then patch package metadata, runtime detection, persistence, or dispatcher behavior as narrowly as possible.

---

### Task 5: Full verification and final review

**Files:**
- Review: all files in `git diff --name-only`

**Interfaces:**
- Consumes: all accepted or repaired subsystem behavior.
- Produces: fresh evidence that the current dirty worktree is internally consistent and CI-ready.

- [ ] **Step 1: Run static checks**

  ```powershell
  python -m ruff check --no-cache app cli entry shared scripts tests
  python -m mypy --no-incremental
  python -m bandit -q -lll -r app cli entry shared -x tests
  ```

- [ ] **Step 2: Run core, UI-contract, performance, and browser suites using the workflow's partitioning**

  Execute the commands from `.github/workflows/python-tests.yml`, with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` where compatible. Every command must exit 0.

- [ ] **Step 3: Review the final diff and workspace status**

  ```powershell
  git diff --check
  git status -sb
  git diff --stat
  ```

  Confirm that only intended user changes, verified fixes, tests, assets, and this acceptance plan are present.
