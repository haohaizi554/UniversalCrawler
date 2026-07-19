# Task 7 Report

Implemented the cancellable release orchestration state machine.

- Added `packaging/release_tool/runner.py` with deterministic stage ordering,
  preflight validation, cancellation checks, redacted terminal events, monotonic
  progress, dry-run planning/skips, and strict JSON request loading.
- Extended release results with failure-stage, cancellation, and redacted error
  state while preserving the existing immutable model contract.
- Added `_build_pipeline_hooks()` in `packaging/build_release.py` to adapt the
  existing versioning, lock, snapshot, build, manifest, proxy, and publisher
  primitives. Direct `main([])` and `main(["--build-only"])` behavior remains
  covered by the existing pipeline tests.
- Kept local/debug builds on the existing binary builder with source immutability
  enforcement disabled, and rejected local manifest key/signing operations during
  preflight.
- Added runner coverage for stage selection, cancellation, dry runs, version
  persistence after failure, redaction, request-file validation, and local mode
  safety. Added a pipeline hook regression test.

## Independent Review Fixes

- Moved the Git identity stage ahead of formal builds. A new release that applies
  a version must persist that version commit and establish the requested local and
  remote tag before the hook opens its immutable source snapshot. The manifest
  continues to use the verified tag commit as `sourceCommit`.
- Kept build-only requests independent from formal tag prerequisites. Portable
  and installer stages now share one request-scoped release lock and build context,
  released reliably by runner cleanup.
- Added explicit, redacted handling for `SystemExit` from stages and cleanup while
  leaving `KeyboardInterrupt` and `GeneratorExit` untouched. Cancellation is
  checked around cleanup and atomically resolved before success, with one terminal
  result event.
- Added a thread-safe active-stage callback for publisher output, so Git, upload,
  and verification logs use the current monotonic stage/progress.
- Bound Windows signer validation to installer builds. A portable-only stage no
  longer probes an installer that it did not build.
- Implemented the documented non-interactive
  `UCrawlCLI.exe --mode cli --help` smoke test with artifact checks, closed stdin,
  captured output, and a 60-second timeout. Smoke failures block success.
- Hardened request loading: unknown field names are not echoed; custom proxy values
  must be endpoint-only URLs or environment references, with no inline credentials,
  path, query, fragment, unsupported scheme, missing port, or invalid port.
- Dry-run preflight now suppresses only the dry-run execution conflict. It still
  validates the complete proposed plan, including upload dependencies, mode rules,
  smoke prerequisites, and source identity requirements, while invoking only the
  version planning hook.

Verification:

`python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_pipeline.py tests/release/packaging/test_release_tool_modes.py tests/release/packaging/test_release_tool_events.py tests/release/packaging/test_release_tool_publisher.py -q`

Result: 310 passed.

`git diff --check`

Result: clean.

The pre-existing untracked `bag_15483236.png` was not modified or staged.
