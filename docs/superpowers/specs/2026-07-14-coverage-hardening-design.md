# Coverage Hardening Design

## Goal

Raise the CI coverage floor from 35% to 70% and add deterministic regression tests around the highest-risk uncovered behavior identified in the 2026-07-14 coverage report.

## Scope

The change adds tests for six live runtime boundaries:

1. Path authorization and destructive WebSocket commands.
2. Bilibili ffmpeg merge process lifecycle.
3. Qt cross-thread acknowledgement and timeout behavior.
4. Xiaohongshu signed HTTP client behavior.
5. Semantic-version precedence edge cases.
6. ApplicationController startup wiring.

The unused zero-coverage compatibility/refactor modules are intentionally not tested or deleted in this change. Production behavior remains unchanged unless a new regression test exposes a concrete defect.

## Considered Approaches

### Raise the total only

This is the smallest change but would leave security, subprocess, and thread boundaries unprotected. Rejected.

### Chase the lowest percentages

This would spend effort on platform entry points and dormant modules while missing more consequential live branches. Rejected.

### Risk-weighted tests plus a ratcheted gate

Add focused tests at live security, process, thread, network, updater, and bootstrap boundaries, then raise the aggregate gate to 70%. Selected because it improves regression detection without coupling tests to third-party services or visible desktop UI.

## Test Design

- Filesystem tests use temporary directories and real path normalization; mocks are limited to cross-drive and symlink/platform conditions that cannot be created portably.
- WebSocket tests call the real dispatcher and assert that unauthorized or malformed payloads never reach controller/workflow mutations.
- Merge tests use a complete fake `Popen` process boundary while exercising the real merge loop, stop, timeout, error-tail, and progress logic.
- Qt tests exercise the real `_GuiRuntimeInvoker`; event delivery is controlled explicitly and no production-only testing hook is added.
- Xiaohongshu tests use complete response/session doubles at the HTTP boundary while exercising real signing, serialization, parsing, and login-state logic.
- Version tests call the real SemVer parser/comparator with precedence-table cases.
- Controller startup uses patched heavyweight constructors but executes the real `ApplicationController.__init__` orchestration.

## CI Contract

The existing branch-enabled coverage command remains unchanged. `coverage report --fail-under=35` becomes `--fail-under=70`. Intentional coverage exclusions are not expanded.

## Success Criteria

- New focused tests pass on the supported Windows/PyQt test environment.
- Existing targeted suites still pass.
- The full non-browser CI-equivalent suite passes.
- The branch-enabled aggregate coverage report is at least 70%.
- No unrelated working-tree files are modified.
