"""供其它宿主执行 CLI 侧运行流程的中立适配器。"""

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
    """通过宿主无关函数运行既有 CLI 搜索流程。"""
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
    """通过宿主无关函数创建既有 SDK 对象。"""
    from shared.sdk_runtime import UcrawlSDK

    return UcrawlSDK(save_dir=save_dir)
