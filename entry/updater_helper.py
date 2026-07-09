"""Standalone updater helper entrypoint.

The GUI process should spawn this helper after it has downloaded and verified an
installer.  The helper intentionally verifies hash and OS signature again before
launching the platform installer, then returns the installer exit code.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.services.secure_updater import InstallerRunner, PackageVerifier, UpdateAsset, log_update_event
from app.services.update_check_service import UPDATE_TRUSTED_PUBLISHERS, UPDATE_TRUSTED_THUMBPRINTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-updater-helper")
    parser.add_argument("--installer", required=True, help="已下载的安装包路径")
    parser.add_argument("--asset-json", required=True, help="manifest asset JSON 文件")
    parser.add_argument("--version", required=True, help="待安装版本")
    parser.add_argument("--log-path", required=True, help="安装器日志输出路径")
    parser.add_argument("--restart-argv-json", default="", help="安装成功后用于重启应用的 argv JSON 数组")
    return parser


def _load_asset(path: str | Path) -> UpdateAsset:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("asset JSON must be an object")
    return UpdateAsset.from_dict(payload)


def _load_restart_argv(value: str) -> list[str]:
    if not str(value or "").strip():
        return []
    payload = json.loads(value)
    if not isinstance(payload, list) or not payload or not all(isinstance(item, str) and item for item in payload):
        raise ValueError("restart argv must be a non-empty string array")
    return payload


def _restart_app_if_requested(argv: list[str]) -> None:
    if not argv:
        return
    subprocess.Popen(argv, shell=False)
    log_update_event("update.install.restart", "restart command launched")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    asset = _load_asset(args.asset_json)
    restart_argv = _load_restart_argv(args.restart_argv_json)
    verifier = PackageVerifier(
        trusted_publishers=UPDATE_TRUSTED_PUBLISHERS,
        trusted_thumbprints=UPDATE_TRUSTED_THUMBPRINTS,
    )
    runner = InstallerRunner(package_verifier=verifier)
    result = runner.run_verified_installer(
        Path(args.installer),
        asset,
        version=str(args.version),
        log_path=Path(args.log_path),
    )
    if result.succeeded:
        _restart_app_if_requested(restart_argv)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
