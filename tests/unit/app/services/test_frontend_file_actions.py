from datetime import datetime
from pathlib import Path

import pytest

from app.services import frontend_file_actions as file_actions


def test_export_latest_debug_log_copies_existing_file(tmp_path):
    source = tmp_path / "latest_debug.log"
    source.write_text("hello", encoding="utf-8")

    target = file_actions.export_latest_debug_log(
        latest_file=source,
        export_root=tmp_path / "exports",
        now=lambda: datetime(2026, 7, 1, 12, 34, 56),
    )

    assert target.name == "latest_debug_20260701_123456.log"
    assert target.read_text(encoding="utf-8") == "hello"


def test_export_latest_debug_log_creates_empty_file_when_source_missing(tmp_path):
    target = file_actions.export_latest_debug_log(
        latest_file=tmp_path / "missing.log",
        export_root=tmp_path / "exports",
        now=lambda: datetime(2026, 7, 1, 12, 34, 56),
    )

    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


def test_truncate_latest_debug_log_ignores_missing_parent(tmp_path):
    target = tmp_path / "latest_debug.log"
    target.write_text("old", encoding="utf-8")

    file_actions.truncate_latest_debug_log(latest_file=target)

    assert target.read_text(encoding="utf-8") == ""


def test_open_file_path_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        file_actions.open_file_path(tmp_path / "missing.mp4")


def test_current_executable_path_uses_frozen_executable(monkeypatch):
    monkeypatch.setattr(file_actions.sys, "frozen", True, raising=False)
    monkeypatch.setattr(file_actions.sys, "executable", r"C:\App\UniversalCrawlerPro.exe")

    assert file_actions.current_executable_path() == r"C:\App\UniversalCrawlerPro.exe"
