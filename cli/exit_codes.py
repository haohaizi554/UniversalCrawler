"""CLI 结构化状态与进程退出码的唯一映射。"""

from __future__ import annotations

from enum import IntEnum


class CliExitCode(IntEnum):
    """供 shell、调度器和自动化脚本使用的稳定退出码。"""

    OK = 0
    ERROR = 1
    USAGE = 2
    TIMEOUT = 124
    CANCELLED = 130


_STATUS_CODES = {
    "ok": CliExitCode.OK,
    "error": CliExitCode.ERROR,
    "usage": CliExitCode.USAGE,
    "timeout": CliExitCode.TIMEOUT,
    "cancelled": CliExitCode.CANCELLED,
}


def exit_code_for_status(status: str) -> CliExitCode:
    """未知状态按运行失败处理，避免编排方误判成功。"""

    return _STATUS_CODES.get(str(status or "").lower(), CliExitCode.ERROR)
