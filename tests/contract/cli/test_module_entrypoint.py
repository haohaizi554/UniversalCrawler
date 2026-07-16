"""`python -m cli` 必须把退出码原样交给操作系统。"""

from __future__ import annotations

import runpy

import pytest

import cli.main


def test_cli_module_entrypoint_forwards_main_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.main, "main", lambda: 7)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("cli", run_name="__main__")

    assert exc_info.value.code == 7
