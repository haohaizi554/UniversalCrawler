"""Standalone updater helper entrypoint.

The GUI process should spawn this helper after it has downloaded and verified an
installer. The helper always re-establishes signed-manifest trust and verifies
the package hash, then applies the configured OS-signature policy immediately
before launching the platform installer.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from app.config.update_trust import (
    UPDATE_PUBLIC_KEY_PEM,
    UPDATE_REQUIRE_OS_SIGNATURE,
    UPDATE_TRUSTED_PUBLISHERS,
    UPDATE_TRUSTED_THUMBPRINTS,
)
from app.services.secure_updater import (
    AssetSelector,
    InstallerRunner,
    PackageVerifier,
    UpdateAsset,
    UpdateManifestVerifier,
    VerificationError,
    compare_semver,
    log_update_event,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-updater-helper")
    parser.add_argument("--installer", required=True, help="已下载的安装包路径")
    parser.add_argument("--manifest", required=True, help="已验证更新清单路径")
    parser.add_argument("--signature", required=True, help="更新清单 Ed25519 签名路径")
    parser.add_argument("--version", required=True, help="待安装版本")
    parser.add_argument("--log-path", required=True, help="安装器日志输出路径")
    parser.add_argument("--restart-argv-json", default="", help="安装成功后用于重启应用的 argv JSON 数组")
    parser.add_argument("--wait-pid", type=int, default=0, help="运行安装器前等待此进程退出")
    return parser


def _load_verified_asset(
    *,
    manifest_path: str | Path,
    signature_path: str | Path,
    expected_version: str,
    os_name: str | None = None,
    arch: str | None = None,
) -> UpdateAsset:
    """Re-establish signed metadata trust inside the standalone helper."""

    manifest = UpdateManifestVerifier(public_key_pem=UPDATE_PUBLIC_KEY_PEM).load_verified(
        Path(manifest_path),
        Path(signature_path),
    )
    if compare_semver(manifest.version, expected_version) != 0:
        raise VerificationError(
            f"signed manifest version {manifest.version} does not match requested version {expected_version}"
        )
    return AssetSelector(os_name=os_name, arch=arch).select(manifest)


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


def _wait_for_process_exit(pid: int, *, timeout_seconds: float = 120.0) -> None:
    """Wait for the GUI process to release installed files before replacement."""

    pid = int(pid or 0)
    if pid <= 0:
        return
    if pid == os.getpid():
        raise RuntimeError("updater helper cannot wait for itself")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error_code = ctypes.get_last_error()
            if error_code == 87:  # ERROR_INVALID_PARAMETER: process already exited.
                return
            raise OSError(error_code, "could not open parent process")
        try:
            result = kernel32.WaitForSingleObject(handle, max(0, int(timeout_seconds * 1000)))
        finally:
            kernel32.CloseHandle(handle)
        if result == 0:  # WAIT_OBJECT_0
            return
        if result == 258:  # WAIT_TIMEOUT
            raise TimeoutError(f"parent process {pid} did not exit before updater timeout")
        raise OSError(ctypes.get_last_error(), "waiting for parent process failed")

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return
            raise
        if time.monotonic() >= deadline:
            raise TimeoutError(f"parent process {pid} did not exit before updater timeout")
        time.sleep(0.1)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    asset = _load_verified_asset(
        manifest_path=args.manifest,
        signature_path=args.signature,
        expected_version=str(args.version),
    )
    restart_argv = _load_restart_argv(args.restart_argv_json)
    _wait_for_process_exit(args.wait_pid)
    verifier = PackageVerifier(
        trusted_publishers=UPDATE_TRUSTED_PUBLISHERS,
        trusted_thumbprints=UPDATE_TRUSTED_THUMBPRINTS,
        require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE,
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
