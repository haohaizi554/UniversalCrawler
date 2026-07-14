# Coverage Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add risk-weighted regression tests and raise the CI aggregate coverage threshold to 70%.

**Architecture:** Keep production interfaces unchanged and test each external boundary through its real orchestration code. Use temporary files and minimal complete doubles for OS, subprocess, Qt-event, and HTTP boundaries so tests remain deterministic and offline.

**Tech Stack:** Python 3.10-3.13, pytest/unittest, unittest.mock, PyQt6, coverage.py, GitHub Actions.

## Global Constraints

- Do not modify `app/ui/pages/log_center_page.py` or `tests/test_unified_frontend_i18n_logs_contract.py` because they contain pre-existing user changes.
- Do not add network access, visible windows, arbitrary sleeps, or test-only production APIs.
- Do not add coverage exclusions.
- Production code may change only if a new test exposes a concrete defect.

---

### Task 1: Path authorization and WebSocket mutation tests

**Files:**
- Create: `tests/test_path_policy.py`
- Modify: `tests/test_websocket_runtime.py`

**Interfaces:**
- Consumes: `PathPolicy.resolve_existing_dir`, `resolve_existing_file`, `resolve_target_path`; `WebSocketMessageDispatcher.handle`.
- Produces: regression coverage for traversal/symlink/cross-drive rejection and guarded change/delete/rename/download dispatch.

- [ ] Add table-oriented path-policy tests for valid descendants, sibling-prefix escape, symlink escape, missing paths/parents, empty roots, and `commonpath` cross-drive failure.
- [ ] Run `python -m pytest tests/test_path_policy.py -q` and verify the new cases execute the previously missing branches.
- [ ] Add async dispatcher tests for invalid types, unauthorized directories, invalid IDs, and successful normalized forwarding.
- [ ] Run `python -m pytest tests/test_websocket_runtime.py tests/test_path_policy.py -q` and require zero failures.

### Task 2: Bilibili merge-process lifecycle tests

**Files:**
- Create: `tests/test_bilibili_merge_process.py`

**Interfaces:**
- Consumes: `BilibiliDownloader._run_merge_process`, `_merge_timeout_seconds`, `_merge_target_size`, `_merge_progress_from_file`.
- Produces: deterministic coverage of ffmpeg success, failure, cancellation, timeout, stderr, and progress behavior.

- [ ] Build a complete fake process with `poll`, `wait`, `terminate`, `kill`, and iterable stderr behavior.
- [ ] Add focused tests for successful exit, non-zero exit with stderr tail, stop with terminate/kill fallback, timeout kill, startup failure, and bounded progress helpers.
- [ ] Run `python -m pytest tests/test_bilibili_merge_process.py -q` and require zero failures.

### Task 3: Xiaohongshu client and SemVer tests

**Files:**
- Create: `tests/test_xiaohongshu_client.py`
- Modify: `tests/test_secure_updater.py`

**Interfaces:**
- Consumes: `XiaohongshuClient` HTTP methods/parser/login probe; `SemVer.parse`, `compare_semver`, and `compare_versions`.
- Produces: offline API-contract tests and a semantic-version precedence table.

- [ ] Add complete response/session doubles and exercise query encoding, signed GET, compact POST JSON, success/error JSON, HTML fallback parsing, login probe tri-state, and close-error isolation.
- [ ] Add SemVer cases for numeric prerelease ordering, numeric-vs-text precedence, identifier length, build metadata, optional `v`, malformed values, and numeric fallback.
- [ ] Run `python -m pytest tests/test_xiaohongshu_client.py tests/test_secure_updater.py tests/test_update_check_service.py -q` and require zero failures.

### Task 4: Qt acknowledgement and controller startup tests

**Files:**
- Create: `tests/test_gui_runtime_invoker.py`
- Modify: `tests/test_application_controller.py`

**Interfaces:**
- Consumes: `_GuiRuntimeInvoker.invoke_and_wait`; `ApplicationController.__init__`.
- Produces: coverage for same-thread execution, queued acknowledgement, callback failure, timeout/cancellation, and startup wiring order/outcomes.

- [ ] Add real invoker tests with controlled signal delivery and bounded waits; assert timeout prevents a late callback mutation.
- [ ] Add a startup smoke test that patches heavyweight services/windows but executes the real constructor and asserts event bus, manager, frontend service, signal wiring, and startup timer selection.
- [ ] Run `python -m pytest tests/test_gui_runtime_invoker.py tests/test_application_controller.py -q` and require zero failures.

### Task 5: CI coverage gate

**Files:**
- Modify: `.github/workflows/python-tests.yml`
- Modify: `tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: current branch-enabled coverage workflow.
- Produces: an asserted `--fail-under=70` repository contract.

- [ ] Change the workflow threshold from 35 to 70.
- [ ] Strengthen the workflow contract test to assert the exact threshold.
- [ ] Run `python -m pytest tests/test_ci_workflow.py -q` and require zero failures.

### Task 6: Integrated verification

**Files:**
- Verify all files changed by Tasks 1-5.

**Interfaces:**
- Consumes: all new tests and the existing CI coverage command.
- Produces: fresh pass/fail and coverage evidence.

- [ ] Run all focused test files together.
- [ ] Run the CI-equivalent non-browser coverage suite and UI-contract chunks.
- [ ] Generate `artifacts/coverage.xml` and run `python -m coverage report --fail-under=70`.
- [ ] Inspect `git diff --check`, `git status --short`, and the final diff; confirm unrelated files are untouched.
