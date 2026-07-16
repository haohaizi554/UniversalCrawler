# Kuaishou Session Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant Kuaishou HTTP/browser navigation, isolate login probes from the browser cookie jar, and prevent degraded authentication snapshots from being persisted.

**Architecture:** Keep the existing request-first and Playwright-fallback pipeline, but make each boundary single-owner and state preserving. Short-link resolution returns reusable response data, browser navigation is idempotent, authentication probes use an isolated API request context, and media capture waits on response events without reloading the page.

**Tech Stack:** Python 3.10+, requests, Playwright sync API, pytest, unittest.mock

## Global Constraints

- Preserve `DomainPolicyEngine` validation for the initial URL and every redirect.
- Preserve Context-level HTTP/WebSocket/Worker/Service Worker network guarding.
- Never log Cookie values; tests may use synthetic values only.
- Do not touch unrelated dirty or untracked workspace files.
- All test modules remain below the canonical suite roots and use `test_*.py` naming.

---

### Task 1: Reuse the short-link response

**Files:**
- Modify: `app/spiders/kuaishou/spider.py`
- Create: `tests/unit/app/spiders/kuaishou/test_share_resolution.py`

**Interfaces:**
- Produces: `_resolve_short_share_url(url: str) -> tuple[str, str | None]`
- Consumes: cached HTML in `_fetch_share_detail_via_http(detail_url, html=None)`

- [ ] **Step 1: Write failing tests** for a short link whose streamed response ends on a detail URL. Assert the response uses `stream=True`, the returned HTML is reused, and only one `requests.get` occurs before direct parsing.
- [ ] **Step 2: Run RED** with `python -m pytest tests/unit/app/spiders/kuaishou/test_share_resolution.py -q`; expect failures because resolution returns only a string and direct parsing performs another request.
- [ ] **Step 3: Implement the minimum behavior**: return final URL plus bounded response text from the short-link request, cache it on the spider for the normalized URL, and let `_fetch_share_detail_via_http` consume that cache before issuing a new GET.
- [ ] **Step 4: Run GREEN** with the same command; expect all tests to pass.

### Task 2: Make browser navigation idempotent

**Files:**
- Modify: `app/spiders/kuaishou/spider.py`
- Create: `tests/unit/app/spiders/kuaishou/test_navigation.py`

**Interfaces:**
- Produces: `_page_matches_target(page, target_url: str) -> bool`
- Consumes: `_navigate_to_target_page(page, context)` and site-search helpers.

- [ ] **Step 1: Write failing tests** showing that a healthy profile URL performs one `goto`, a keyword flow performs one homepage `goto`, and query parameter reordering still counts as the same target.
- [ ] **Step 2: Run RED** with `python -m pytest tests/unit/app/spiders/kuaishou/test_navigation.py -q`; expect duplicate navigation assertions to fail.
- [ ] **Step 3: Implement the minimum behavior**: compare normalized scheme/host/path/query, reuse the current page when it already matches, and make search helpers skip homepage navigation when already there.
- [ ] **Step 4: Run GREEN** with the same command and the existing Kuaishou helper tests.

### Task 3: Isolate session validation and guard persistence

**Files:**
- Modify: `app/spiders/kuaishou/spider.py`
- Modify: `tests/unit/app/spiders/kuaishou/test_auth_persistence.py`

**Interfaces:**
- Produces: `_profile_session_valid(playwright, context) -> bool | None`
- Produces: `_authenticated_snapshot_is_safe(previous_state, current_state) -> bool`

- [ ] **Step 1: Write failing tests** asserting that the probe uses `playwright.request.new_context(storage_state=...)`, never touches `page.request`, disposes the isolated request context, and rejects persistence when a previous main-site `userId` disappears.
- [ ] **Step 2: Run RED** with `python -m pytest tests/unit/app/spiders/kuaishou/test_auth_persistence.py -q`; expect current shared-jar and unconditional-save behavior to fail.
- [ ] **Step 3: Implement the minimum behavior**: pass the Playwright owner into session methods, construct an isolated request context from a fresh context snapshot, dispose it in `finally`, and compare authentication Cookie keys before `save_json_file`.
- [ ] **Step 4: Run GREEN** with the same command and verify manual first-login persistence remains allowed.

### Task 4: Replace reload-based media capture with event waiting

**Files:**
- Modify: `app/spiders/kuaishou/spider.py`
- Create: `tests/unit/app/spiders/kuaishou/test_detail_capture.py`

**Interfaces:**
- Produces: `_wait_for_detail_stream(page, event, timeout_ms: int) -> bool`
- Consumes: `_capture_single_detail_page(page, initial_stream_urls=())`

- [ ] **Step 1: Write failing tests** asserting an immediate response completes without a sleep, a response after play click completes through the event, and an exhausted wait never calls `page.reload`.
- [ ] **Step 2: Run RED** with `python -m pytest tests/unit/app/spiders/kuaishou/test_detail_capture.py -q`; expect reload and fixed-wait assertions to fail.
- [ ] **Step 3: Implement the minimum behavior** using `threading.Event`, bounded 100 ms interruptible waits, and DOM rechecks after play. Remove the routine reload branch.
- [ ] **Step 4: Run GREEN** with the same command.

### Task 5: Regression and governance verification

**Files:**
- Modify only if required by discovered regressions: the files listed in Tasks 1-4.

**Interfaces:**
- Consumes all preceding task behavior.
- Produces a verified Kuaishou runtime with no suite-layout violations.

- [ ] **Step 1: Run focused regression**: `python -m pytest tests/unit/app/spiders/kuaishou tests/unit/app/spiders/test_helpers.py tests/unit/app/services/test_auth_service.py -q`.
- [ ] **Step 2: Run network/security regression**: `python -m pytest tests/unit/shared/network tests/unit/shared/test_runtime_helpers.py tests/support/browser_cases/network_guard.py -q`.
- [ ] **Step 3: Run suite governance**: `python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q` and `python -m pytest tests --collect-only -q`.
- [ ] **Step 4: Run static checks**: `python -m ruff check app/spiders/kuaishou/spider.py tests/unit/app/spiders/kuaishou` and `python -m compileall app/spiders/kuaishou tests/unit/app/spiders/kuaishou`.
- [ ] **Step 5: Review `git diff --check`, confirm no unrelated file is staged, and report any real-browser validation that remains unavailable.
