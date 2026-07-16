# Test Suite Taxonomy and Naming Design

## Problem

The test launcher currently classifies files by a growing collection of filename globs in `tests/test_registry.py`. A file name therefore has to encode both the production subject and the suite that should execute it. New platform tests such as `test_missav_challenge_browser.py` and `test_kuaishou_auth_persistence.py` do not match an existing prefix even though they are ordinary isolated tests, so CI requires another registry exception.

The same directory also contains support modules named `test_launcher.py`, `test_registry.py`, and `test_runner.py`. They must be explicitly excluded from collection and still generate pytest collection warnings in some invocation modes.

## Decision

Use three independent dimensions:

1. The first directory below `tests/` defines the test suite.
2. The remaining directory path mirrors the production namespace or stable product boundary.
3. Registered pytest markers describe runtime capabilities and constraints, never product names.

The canonical test suites are:

| Root | Responsibility |
| --- | --- |
| `tests/unit/` | Isolated, deterministic tests with external boundaries replaced by fakes or mocks |
| `tests/integration/` | Multiple real project components or local process/storage boundaries working together |
| `tests/contract/` | Public API, CLI, configuration, frontend, protocol, and compatibility contracts |
| `tests/e2e/` | Complete entry-point or real-browser user journeys |
| `tests/architecture/` | Static dependency, layout, size, and repository fitness rules |
| `tests/performance/` | Explicit performance budgets and benchmarks |
| `tests/release/` | Packaging, installer, updater, CI, and release-asset validation |
| `tests/testkit/` | Tests of the repository's test catalog, launcher, and runner |

Non-test helpers live under `tests/support/` and must not start with `test_`. Global pytest fixtures remain in `tests/conftest.py` because pytest assigns special semantics to that file.

## Naming grammar

Test modules use:

```text
tests/<suite>/<production namespace>/test_<observable responsibility>.py
```

The suite and namespace must not be repeated in the filename when the path already communicates them. Examples:

```text
tests/unit/app/spiders/missav/test_challenge_browser.py
tests/unit/app/spiders/kuaishou/test_auth_persistence.py
tests/unit/app/ui/components/test_media_preview_panel.py
tests/contract/web/test_fastapi_endpoints.py
tests/e2e/web/test_browser_journeys.py
tests/release/packaging/test_assets.py
```

Test classes use `Test<CapabilityOrScenario>`. Test functions and methods use `test_<observable_result>_when_<condition>` when a condition matters, or `test_<observable_behavior>` otherwise. Names such as `test_case_1`, `test_fix`, `test_new`, and `test_works` are rejected by the layout contract.

## Runtime markers

Markers are limited to cross-cutting runtime properties:

- `browser`
- `gui`
- `network`
- `slow`
- `serial`
- `windows`
- `security`
- existing `architecture` and `benchmark`

All markers are registered in `pyproject.toml`, and `strict_markers = true` makes misspellings a collection error. Business domains such as `bilibili`, `kuaishou`, and `missav` are paths, not markers.

## Catalog and launcher

The catalog scans canonical suite roots. Built-in categories are declared once from directory roots; no built-in category accepts exact files, filename-prefix lists, or exclusion lists. Plugin APIs may still accept explicit external files because they model user-supplied extensions rather than built-in classification.

`auto_discover_tests()` changes meaning: it reports any collected test outside a canonical suite root. `misc` remains only as a compatibility view during the migration implementation and must be empty when the migration finishes.

The canonical support modules are:

```text
tests/launcher.py
tests/support/catalog.py
tests/support/runner.py
```

The public `entry/test_entry.py` integration imports these modules directly. Existing launcher category identifiers are replaced with suite identifiers so command-line, TUI, and GUI selection all use the same taxonomy.

## Migration policy

This change is a complete migration, not a permanent compatibility layer:

- Every collected test module moves below one canonical suite root.
- Test helper modules move below `tests/support/`.
- CI commands select suite directories and marker expressions rather than ignore lists tied to filenames.
- Active documentation and scripts are updated to canonical paths.
- Historical review and implementation-plan records remain historical and are not rewritten.
- An architecture contract prevents new root-level tests and prevents reintroduction of built-in filename allowlists.

## Agent policy

`tests/AGENTS.md` is the durable instruction boundary for any agent modifying the test tree. It requires suite-first placement, production-path mirroring, registered runtime markers, and the validation commands. It explicitly prohibits adding an exact built-in filename or business-prefix glob to make CI pass.

## References

- pytest good integration practices: <https://docs.pytest.org/en/stable/explanation/goodpractices.html>
- pytest marker registration and selection: <https://docs.pytest.org/en/stable/how-to/mark.html>
- Bazel Test Encyclopedia: <https://bazel.build/reference/test-encyclopedia>
- Google Testing Blog, Test Sizes: <https://testing.googleblog.com/2010/12/test-sizes.html>
