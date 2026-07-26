"""Regression tests for the per-file pytest process runner."""

from __future__ import annotations

import subprocess

from tests.support import runner


def test_run_category_forces_consistent_utf8_for_nested_subprocesses(monkeypatch):
    """Windows 父子 Python 必须使用同一编码，避免 UTF-8 输出被按 GBK 解码。"""

    captured_environment: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured_environment.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout="1 passed in 0.01s\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_category(
        "testkit",
        "testkit",
        ["tests/testkit/test_runner.py"],
    )

    assert result.success is True
    assert captured_environment["PYTHONIOENCODING"] == "utf-8"
    assert captured_environment["PYTHONUTF8"] == "1"
