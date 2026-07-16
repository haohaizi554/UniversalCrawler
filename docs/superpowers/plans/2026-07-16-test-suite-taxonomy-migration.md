# Test Suite Taxonomy Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely migrate the repository test tree from filename-glob classification to canonical suite directories with enforceable naming, marker, CI, documentation, and Agent contracts.

**Architecture:** `tests/support/catalog.py` discovers tests from eight fixed suite roots and exposes the existing launcher/plugin API without built-in file allowlists. Test paths carry suite and production ownership; pytest markers carry runtime constraints. A repository architecture test enforces the layout so future tests cannot regress to root-level files or one-off registry entries.

**Tech Stack:** Python 3.10+, pytest, unittest compatibility, pathlib, PyQt6 test launcher, GitHub Actions.

## Global Constraints

- Work in `D:\desktop\project\UniversalCrawlerProplus`; do not create a worktree or external copy.
- Preserve all pre-existing uncommitted changes and keep them out of the migration commit.
- Migrate every collected `test_*.py` module; no permanent legacy manifest or root-level exception is allowed.
- Keep `tests/conftest.py` at the test root.
- Built-in suites may be selected only by canonical directory roots; exact file lists and business-prefix globs remain available only to plugin APIs.
- Runtime markers must be registered and `strict_markers = true` must be enabled.
- Historical files under `docs/superpowers/` are records and are not bulk-rewritten after this plan and design are added.

---

### Task 1: Add the failing taxonomy contract

**Files:**
- Create: `tests/architecture/test_test_suite_layout.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: repository filesystem rooted at `tests/` and pytest configuration from `pyproject.toml`.
- Produces: architecture failures for non-canonical collected tests, unregistered runtime markers, support modules beginning with `test_`, and built-in filename allowlists.

- [ ] **Step 1: Write failing layout tests**

Add tests that assert the only collected roots are `unit`, `integration`, `contract`, `e2e`, `architecture`, `performance`, `release`, and `testkit`; that no `tests/test_*.py` file exists; that support modules do not begin with `test_`; and that the built-in catalog declarations contain directory roots without `files`, `exclude`, or business-prefix patterns.

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
python -m pytest tests/architecture/test_test_suite_layout.py -q
```

Expected: failures list the current root-level test modules and the current glob-driven registry.

- [ ] **Step 3: Register runtime markers strictly**

Set `strict_markers = true` and register `browser`, `gui`, `network`, `slow`, `serial`, `windows`, and `security` alongside `architecture` and `benchmark`.

### Task 2: Replace the built-in filename registry with a suite catalog

**Files:**
- Rename: `tests/test_registry.py` to `tests/support/catalog.py`
- Rename: `tests/test_runner.py` to `tests/support/runner.py`
- Rename: `tests/test_launcher.py` to `tests/launcher.py`
- Create: `tests/support/__init__.py`
- Modify: `entry/test_entry.py`
- Modify: `tests/run_all_tests.py`
- Modify: `tests/run_core_suite.py`
- Test: `tests/testkit/test_catalog.py`
- Test: `tests/testkit/test_launcher_ui.py`
- Test: `tests/testkit/test_runtime_isolation.py`

**Interfaces:**
- Produces: `SuiteDefinition`, `BUILTIN_SUITES`, `discover_test_files()`, `get_resolved_files()`, `auto_discover_tests()`, and the existing plugin registration functions from `tests.support.catalog`.
- Consumes: suite roots relative to the project root and plugin directories supplied at runtime.

- [ ] **Step 1: Move the infrastructure modules to non-collectable names**

Use package imports (`from tests.support.catalog ...`, `from tests.support.runner ...`) in the launcher, entry point, runners, and tests. Keep plugin registration behavior backward-compatible at the function level.

- [ ] **Step 2: Make built-in suite declarations root-only**

Declare exactly these built-in roots:

```python
BUILTIN_SUITE_ROOTS = {
    "unit": "tests/unit",
    "integration": "tests/integration",
    "contract": "tests/contract",
    "e2e": "tests/e2e",
    "architecture": "tests/architecture",
    "performance": "tests/performance",
    "release": "tests/release",
    "testkit": "tests/testkit",
}
```

`get_resolved_files("all")` returns the deduplicated union; `auto_discover_tests()` returns files outside those roots; plugin categories continue to resolve their own explicit files or directory patterns.

- [ ] **Step 3: Update catalog tests for directory discovery**

Replace assertions about `cli_sdk`, `web_api`, `core_services`, and per-file globs with assertions about all eight suites, nested automatic discovery, empty unassigned output, and plugin isolation.

- [ ] **Step 4: Run focused catalog and entry tests**

Run:

```powershell
python -m pytest tests/testkit/test_catalog.py tests/testkit/test_runtime_isolation.py -q
```

Expected: all pass with no collection warnings for catalog, runner, or launcher classes.

### Task 3: Move all tests into canonical suites and namespaces

**Files:**
- Move all current root-level `tests/test_*.py` modules below canonical roots.
- Move `tests/web_browser_cases/`, `tests/web_browser_support.py`, `tests/web_test_app.py`, `tests/frontend_static_assets.py`, and `tests/unified_frontend_contract_support.py` below `tests/support/`.
- Create package `__init__.py` files for every namespace containing tests or imported support code.
- Modify imports and path literals in moved tests.

**Interfaces:**
- Consumes: the suite selection criteria from the approved design.
- Produces: zero root-level `test_*.py` files and zero tests reported by `auto_discover_tests()`.

- [ ] **Step 1: Move isolated tests**

Move mock/fake-driven application behavior under `tests/unit/app/...`, shared utilities under `tests/unit/shared/...`, and CLI implementation tests under `tests/unit/cli/...`. In particular:

```text
tests/test_missav_challenge_browser.py -> tests/unit/app/spiders/missav/test_challenge_browser.py
tests/test_kuaishou_auth_persistence.py -> tests/unit/app/spiders/kuaishou/test_auth_persistence.py
tests/test_media_preview_panel.py -> tests/unit/app/ui/components/test_media_preview_panel.py
```

- [ ] **Step 2: Move integration, contract, and E2E tests**

Move multi-component runtime flows to `tests/integration/`, public/configuration/frontend protocol checks to `tests/contract/`, full entry flows to `tests/e2e/app/`, and the real Playwright aggregator to `tests/e2e/web/test_browser_journeys.py`.

- [ ] **Step 3: Move performance, release, and testkit tests**

Move the benchmark module to `tests/performance/test_runtime_budgets.py`; packaging, CI, updater, and bootstrap validation to `tests/release/`; and suite infrastructure tests to `tests/testkit/`.

- [ ] **Step 4: Move and re-import support code**

Use `tests.support.browser_cases`, `tests.support.browser_runtime`, `tests.support.web_test_app`, `tests.support.frontend_static_assets`, and `tests.support.unified_frontend_contract` as the canonical helper imports.

- [ ] **Step 5: Verify collection identity and coverage**

Run:

```powershell
python -m pytest tests --collect-only -q
python tests/launcher.py --list
```

Expected: every test collects once, all eight built-in suites are listed, and `auto_discover_tests()` is empty.

### Task 4: Update CI and active scripts to select suites structurally

**Files:**
- Modify: `.github/workflows/python-tests.yml`
- Modify: `scripts/update_bootstrap.py`
- Modify: `tests/release/ci/test_workflow.py`
- Modify: `tests/release/packaging/test_assets.py`

**Interfaces:**
- Consumes: canonical suite roots and `browser`/`benchmark` markers.
- Produces: non-browser coverage, isolated performance execution, isolated Chromium execution, and structural quality gates without filename ignore lists.

- [ ] **Step 1: Update the quality job**

Run architecture and CI contract paths from their new roots.

- [ ] **Step 2: Replace file-specific coverage ignores**

Select `tests/unit tests/integration tests/contract tests/e2e/app tests/release tests/testkit tests/architecture` for the core coverage job; run `tests/performance` separately; run `tests/e2e/web` in the Chromium job.

- [ ] **Step 3: Update CI contract assertions**

Assert canonical suite paths and the absence of old `--ignore=tests/test_web_browser.py`, performance filename, and unified-frontend filename-glob exclusions.

- [ ] **Step 4: Run release/CI tests**

Run:

```powershell
python -m pytest tests/release -q
```

Expected: all release and workflow contract tests pass.

### Task 5: Establish durable naming and Agent constraints

**Files:**
- Create: `tests/AGENTS.md`
- Rewrite in place: `tests/NAMING.md`
- Modify: `tests/README.md`
- Modify: `docs/guides/testing.md`
- Modify: `docs/guides/development.md`
- Modify: `docs/guides/packaging.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `packaging/README.md`
- Modify: `mermaid/09-testing-and-quality.md`

**Interfaces:**
- Produces: a single documented source of truth for humans and repository-aware agents.

- [ ] **Step 1: Write `tests/AGENTS.md`**

Require suite-first placement, production namespace mirroring, behavior names, registered runtime markers, no built-in file allowlists, and exact pre-submit commands.

- [ ] **Step 2: Adapt the naming and testing guides**

Document the eight suites, examples, marker policy, helper policy, catalog API, launcher commands, and migration-complete status. Preserve unrelated guidance rather than rewriting other project documentation.

- [ ] **Step 3: Update active path references**

Replace old launcher, catalog, runner, and moved test paths in active READMEs and engineering guides. Do not alter historical `docs/superpowers/` records.

### Task 6: Verify, review, and publish the migration

**Files:**
- All files changed by Tasks 1-5.

**Interfaces:**
- Produces: evidence that the migration is complete and does not absorb unrelated working-tree changes.

- [ ] **Step 1: Run static and taxonomy checks**

```powershell
python -m pytest tests/architecture tests/testkit tests/release/ci -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

- [ ] **Step 2: Run the non-browser suite with coverage**

Use the same suite paths and coverage threshold as `.github/workflows/python-tests.yml`; require at least 70 percent total coverage.

- [ ] **Step 3: Run performance and browser suites separately**

```powershell
python -X faulthandler -m pytest tests/performance -q
python -X faulthandler -m pytest tests/e2e/web -q
```

- [ ] **Step 4: Inspect the final diff**

Confirm no root-level tests, no built-in exact-file rules, no stale active paths, and no unrelated user files staged. Preserve unstaged user modifications at their migrated paths.

- [ ] **Step 5: Commit and push only migration changes**

Create a focused commit with message `test: migrate suites to canonical taxonomy`, then push the current branch. Do not stage `code_report.html`, deleted screenshots, application/player changes, or the user's unstaged portions of moved test helpers.
