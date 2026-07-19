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

## Third Review Fixes

- Split source identity from publication. `SOURCE_IDENTITY` now establishes an
  applied-version commit, required main push, and release tag before the immutable
  source snapshot. The remote Release itself runs only in `PUBLISHING`, after
  local builds, manifest signing, and the explicit `SMOKE_TESTING` stage.
- Added preflight validation that release creation or repair always includes
  release notes, including dry-run plan validation. A new release that applies
  and commits a version before tagging must also push main, so the remote tag
  cannot point at an unreachable commit.
- `KeyboardInterrupt` and `GeneratorExit` now propagate unchanged after exactly
  one cleanup attempt. Cleanup failures are suppressed on that interruption path,
  preserving the original interruption while releasing request-scoped resources.
- Added runner and real hook integration coverage for the source identity,
  signed artifact, smoke, publication order; smoke failure prevents remote Release
  creation. Added preflight and interruption probes.

## Fourth Review Fixes

- A `NEW_RELEASE` that creates or updates a public Release now requires the full
  formal chain: version application and commit, main push, release tag, portable
  and installer builds, manifest signing, smoke testing, and release notes.
  Same-release repair retains its existing repair path and is not forced through
  a new-version publication chain.
- Runner preflight now invokes a read-only dependency hook for both real and
  dry-run requests. It validates release notes, private-key references and
  repository-external key safety, and public-key availability before any lock,
  version write, or remote operation. Non-dry requests then run a request-scoped
  preparation hook that acquires the shared release lock before version mutation.
- Formal new releases reject a dirty Git worktree or index before applying a
  version. Version commits use `git commit --only -- <version paths>`, reject
  unexpected staged or unstaged files, and revalidate the committed path set and
  clean baseline before push and tag operations.
- Public-key uploads now persist the exact selected upload set and remote asset
  verification consumes that same set. Missing, unreadable, empty, or invalid PEM
  public keys fail during preflight rather than allowing a partial publication.
- Added temporary-repository coverage for a pre-staged unrelated file, dry-run
  dependency validation without lock acquisition, public-key upload/verification
  parity, and missing or malformed public keys.

## Fifth Review Fixes

- Public `NEW_RELEASE` creation now also requires release asset upload and remote
  asset verification, closing the remaining metadata-only publication path.
- Clean Git baseline enforcement now applies to every real `NEW_RELEASE` request
  capable of version mutation, source identity, or binary builds, including
  non-public requests, before version application begins.
- Main is pushed from the exact verified version commit using an explicit
  `<commit>:refs/heads/main` refspec. The hook rejects HEAD races before push and
  verifies that remote main resolves to the same full commit afterward.
- Private-key preflight now reads and parses a non-empty Ed25519 private PEM.
  Missing, unreadable, empty, malformed, public-only, or wrong-curve key material
  fails inside runner-owned preflight with generic, redacted errors.
- Proxy environment resolution and GitHub publisher construction are lazy
  preflight dependencies, so missing proxy references and invalid repositories
  emit exactly one terminal failure result and perform no lock, mutation, or
  remote operation.
- `proxy_label` now accepts only project-defined named choices or a syntactically
  valid environment reference. Arbitrary URLs and credential-bearing values are
  rejected generically; `custom_proxy` remains the sole explicit endpoint field.

Verification:

`python -m pytest tests/release/packaging/test_release_tool_runner.py tests/release/packaging/test_release_pipeline.py tests/release/packaging/test_release_tool_modes.py tests/release/packaging/test_release_tool_events.py tests/release/packaging/test_release_tool_publisher.py -q`

Result: 336 passed.

`git diff --check`

Result: clean.

The pre-existing untracked `bag_15483236.png` was not modified or staged.
