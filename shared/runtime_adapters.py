"""Neutral adapters that execute CLI-facing runtime flows for other hosts."""

from __future__ import annotations

from typing import Any


def run_cli_search(
    *,
    source: str,
    keyword: str,
    save_dir: str,
    selection_strategy,
    config: dict,
    timeout: float | None,
    download: bool,
) -> dict[str, Any]:
    """Run the existing CLI search workflow behind a host-neutral function."""
    from shared.cli_runner_runtime import CLIRunner

    runner = CLIRunner(
        source=source,
        keyword=keyword,
        save_dir=save_dir,
        selection_strategy=selection_strategy,
        config=config,
        verbose=False,
        log_to_stderr=False,
        timeout=timeout,
        download=download,
    )
    return runner.run()


def build_sdk(*, save_dir: str):
    """Create the existing SDK object behind a host-neutral function."""
    from shared.sdk_runtime import UcrawlSDK

    return UcrawlSDK(save_dir=save_dir)
