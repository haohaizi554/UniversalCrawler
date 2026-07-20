"""Inno Setup 安装器构建隔离、重试和原子发布契约。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.support.paths import PROJECT_ROOT

PACKAGING_DIR = PROJECT_ROOT / "packaging"
BUILD_INSTALLER_TOOL = PACKAGING_DIR / "build_installer.py"
INSTALLER_FILE = PACKAGING_DIR / "installer.iss"


def _load_build_installer_tool():
    spec = importlib.util.spec_from_file_location(
        "ucrawl_build_installer_resilience_tool",
        BUILD_INSTALLER_TOOL,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(PACKAGING_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_transient_resource_update_retries_in_isolated_workspace(tmp_path):
    tool = _load_build_installer_tool()
    output_dir = tmp_path / "installer"
    output_dir.mkdir()
    final_installer = output_dir / "setup.exe"
    final_installer.write_bytes(b"previous-installer")
    attempt_dirs: list[Path] = []

    def fake_stream(command, *, cwd):
        assert cwd == tool.PROJECT_ROOT / "packaging"
        output_argument = next(
            item for item in command if item.startswith("/DOutputDir=")
        )
        attempt_dir = Path(output_argument.split("=", 1)[1])
        attempt_dirs.append(attempt_dir)
        assert final_installer.read_bytes() == b"previous-installer"
        if len(attempt_dirs) == 1:
            return (
                2,
                "Resource update error: EndUpdateResource failed, "
                "try excluding the Output folder from your antivirus software (110)\n",
            )
        (attempt_dir / final_installer.name).write_bytes(b"new-installer")
        return 0, "Successful compile\n"

    with (
        patch.object(tool, "OUTPUT_DIR", output_dir),
        patch.object(tool, "_stream_iscc", side_effect=fake_stream),
        patch.object(tool.time, "sleep") as sleep,
    ):
        tool._compile_installer_with_retry("iscc", final_installer)

    assert len(attempt_dirs) == 2
    assert attempt_dirs[0] != attempt_dirs[1]
    assert final_installer.read_bytes() == b"new-installer"
    assert not any(path.exists() for path in attempt_dirs)
    sleep.assert_called_once()


def test_non_transient_compiler_error_is_not_retried(tmp_path):
    tool = _load_build_installer_tool()
    output_dir = tmp_path / "installer"
    output_dir.mkdir()
    final_installer = output_dir / "setup.exe"
    final_installer.write_bytes(b"previous-installer")

    with (
        patch.object(tool, "OUTPUT_DIR", output_dir),
        patch.object(
            tool,
            "_stream_iscc",
            return_value=(2, "Error in installer.iss: unknown directive\n"),
        ) as stream,
        patch.object(tool.time, "sleep") as sleep,
        pytest.raises(subprocess.CalledProcessError),
    ):
        tool._compile_installer_with_retry("iscc", final_installer)

    assert stream.call_count == 1
    sleep.assert_not_called()
    assert final_installer.read_bytes() == b"previous-installer"


def test_installer_script_accepts_isolated_output_directory():
    source = INSTALLER_FILE.read_text(encoding="utf-8")
    assert "#ifndef OutputDir" in source
    assert "OutputDir={#OutputDir}" in source
