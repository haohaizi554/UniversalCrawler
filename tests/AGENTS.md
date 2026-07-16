# Test Suite Engineering Contract

These instructions apply to every file below `tests/`. They are the durable source of truth for humans and repository-aware agents adding, moving, or reviewing tests.

## Non-negotiable layout

Every collected test module belongs below exactly one canonical suite root:

| Root | Use it when |
| --- | --- |
| `tests/unit/` | One unit of behavior is isolated; external processes, networks, browsers, clocks, and persistent storage are replaced or controlled. |
| `tests/integration/` | Multiple real project components or local process/storage boundaries collaborate. |
| `tests/contract/` | A public API, CLI, configuration, frontend protocol, entry point, or compatibility promise is being verified. |
| `tests/e2e/` | A complete user journey crosses a real application entry point or browser. |
| `tests/architecture/` | The test statically enforces dependency, layout, size, naming, or repository fitness rules. |
| `tests/performance/` | The assertion is a timing, throughput, allocation, or performance budget. |
| `tests/release/` | The subject is CI, packaging, installation, updating, or release assets. |
| `tests/testkit/` | The subject is the test catalog, launcher, runner, plugin API, or test infrastructure itself. |

The path after the suite root mirrors the production namespace or a stable external boundary:

```text
tests/<suite>/<production namespace>/test_<observable responsibility>.py
```

Examples:

```text
tests/unit/app/spiders/missav/test_challenge_browser.py
tests/integration/app/core/downloaders/m3u8/test_lifecycle.py
tests/contract/web/test_fastapi_endpoints.py
tests/e2e/web/test_browser_journeys.py
tests/release/packaging/test_assets.py
```

Do not add collected `tests/test_*.py` files at the test root. Keep reusable non-test helpers under `tests/support/` without a `test_` prefix. Keep the root `tests/conftest.py`, `tests/launcher.py`, and `tests/run_*.py` support entry points non-collectable.

## Classification rules

- Choose a suite by isolation level and observable responsibility, not by product name, platform, filename prefix, current CI job, or implementation convenience.
- Do not repeat the suite or full production path in a filename when the parent directories already express it.
- Built-in suites are directory-driven. Never add an exact file, filename-prefix glob, include rule, exclude rule, or business-domain whitelist to make a built-in suite pass.
- Explicit files and globs are allowed only for runtime plugin/extension categories outside the built-in suite taxonomy.
- `misc` is a disabled violation view, not a destination. `auto_discover_tests()` must remain empty.
- A genuinely new suite requires an architecture decision plus coordinated changes to the catalog, CI, launcher, architecture contract, and active documentation. Prefer an existing suite unless its responsibility truly differs.

## Names and markers

- Modules: `test_<observable responsibility>.py`.
- Classes: `Test<CapabilityOrScenario>`.
- Functions/methods: `test_<observable behavior>` or `test_<observable result>_when_<condition>`.
- Do not use ambiguous names such as `test_case_1`, `test_fix`, `test_new`, `test_misc`, or `test_works`.
- Markers describe cross-cutting runtime constraints only: `architecture`, `benchmark`, `browser`, `gui`, `network`, `security`, `serial`, `slow`, and `windows`.
- Do not create markers for business domains or platforms such as Bilibili, Kuaishou, MissAV, Web API, or downloader names. Those belong in paths.
- Register every new marker in `pyproject.toml`; strict marker validation must remain enabled.

## Change workflow

1. Identify the behavioral owner and isolation level before choosing a path.
2. Mirror the production namespace below the selected suite root.
3. Add focused tests first; keep helpers in `tests/support/` when reused across suites.
4. Run the narrow test while iterating.
5. Run the taxonomy, catalog, and collection contracts before handoff:

```powershell
python -m pytest tests/architecture/test_test_suite_layout.py tests/testkit/test_catalog.py -q
python tests/launcher.py --list
python -m pytest tests --collect-only -q
```

6. Run the affected suite. Run `tests/performance/` without coverage instrumentation and `tests/e2e/web/` in the browser environment. Changes that affect CI coverage must preserve the configured 70 percent gate.

Launcher changes must keep all eight suite cards visible through scrolling, keep section counts derived from the catalog, prevent horizontal overflow, and remain usable at the configured 90%, 100%, 110%, and 125% UI scales.

Update active guides when commands or canonical paths change. Do not rewrite historical records under `docs/superpowers/` to make old plans look current.
