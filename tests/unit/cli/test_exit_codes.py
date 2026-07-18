"""CLI 进程退出码必须稳定映射结构化状态。"""

from __future__ import annotations

import pytest

from cli.exit_codes import CliExitCode, exit_code_for_status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ok", CliExitCode.OK),
        ("error", CliExitCode.ERROR),
        ("usage", CliExitCode.USAGE),
        ("timeout", CliExitCode.TIMEOUT),
        ("cancelled", CliExitCode.CANCELLED),
    ],
)
def test_statuses_map_to_stable_process_codes(
    status: str,
    expected: CliExitCode,
) -> None:
    assert exit_code_for_status(status) is expected


def test_unknown_status_is_a_runtime_error() -> None:
    assert exit_code_for_status("unexpected") is CliExitCode.ERROR
