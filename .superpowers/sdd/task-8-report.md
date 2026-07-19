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
