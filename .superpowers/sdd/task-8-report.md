# Task 8 Report

## Result

DONE. Added GUI and headless release script routing while retaining `main()` as
the programmatic legacy headless API.

## Behavior

- Script invocation opens the panel with no arguments or `--gui`; panel import
  stays lazy until Task 10 provides the module.
- `--headless --request-file` loads the existing strict JSON request contract,
  deletes the temporary request file in `finally`, and runs the unified runner.
- `--dry-run` creates a non-mutating request through that same runner.
- Legacy command-line options retain their original path through `main()`;
  `--headless` alone is removed only before legacy parsing.

## Verification

- RED: focused entry-point tests failed because the new script-routing APIs
  did not yet exist.
- GREEN: focused entry-point tests passed (`9 passed`).
- `python -m pytest tests/release/packaging/test_release_pipeline.py -v`
  - `70 passed in 16.17s`.
- `python -m ruff check packaging/build_release.py tests/release/packaging/test_release_pipeline.py`
  - Passed.
- `git diff --check`
  - Passed.

## Security

Request files use the existing strict loader, which rejects unknown fields and
inline private-key material. The temporary request file is deleted after its
read attempt, including validation failures. No credential contents are logged
or recorded here.

## Important Review Fixes

- Dry-run requests now provide a known equal remote version and explicitly
  disable every mutating or dependent action. Both build-only states complete
  through the unified runner as read-only plans.
- Dry-run and request-file routes reject unsupported or conflicting arguments
  with argparse status 2 and generic messages. Ordinary headless legacy routing
  still forwards every legacy token unchanged.
- Invalid and malformed request files are deleted before failure handling. The
  unified runner owns the resulting preflight failure and emits one redacted
  terminal result without an uncaught traceback.

### Review Verification

- RED: focused review regressions produced `10 failed, 1 passed`, with failures
  corresponding to all three review findings.
- GREEN: the same focused selection passed (`11 passed`).
- `python -m pytest tests/release/packaging/test_release_pipeline.py -q`
  - `79 passed in 15.29s`.
- `python -m ruff check packaging/build_release.py tests/release/packaging/test_release_pipeline.py`
  - Passed.
- `git diff --check`
  - Passed.
