"""独立更新辅助进程入口。

GUI 进程下载并验证安装包后再启动此辅助进程。跨进程不能继承内存中的验证
结论，因此辅助进程必须重新验证签名清单与包哈希，并在启动平台安装器前
立即执行配置的 OS 签名策略。
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import traceback
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
    log_update_event,
)
from app.services.update_check_service import (
    REVISION_AUTH_TOKEN_ENV,
    REVISION_AUTH_TTL_SECONDS,
)
from shared.release_identity import ReleaseIdentity, load_runtime_release_identity

_ALLOWED_RESTART_EXECUTABLES = frozenset(
    {
        "universalcrawlerpro.exe",
        "crawlerwebportal.exe",
        "ucrawllauncher.exe",
    }
)


def _best_effort_update_log(event: str, message: str, *, level: str = "INFO", **details: object) -> None:
    """遥测故障不能阻断安装器交接、失败落盘或安装后的应用重启。"""

    try:
        log_update_event(event, message, level=level, **details)
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-updater-helper")
    parser.add_argument("--installer", default="", help="已下载的安装包路径")
    parser.add_argument("--manifest", default="", help="已验证更新清单路径")
    parser.add_argument("--signature", default="", help="更新清单 Ed25519 签名路径")
    parser.add_argument("--version", default="", help="待安装版本")
    parser.add_argument("--release-revision", type=int, default=0, help="待安装发布修订号")
    parser.add_argument("--log-path", default="", help="安装器日志输出路径")
    parser.add_argument("--install-dir", default="", help="当前冻结应用安装目录")
    parser.add_argument("--restart-argv-json", default="", help="安装成功后用于重启应用的 argv JSON 数组")
    parser.add_argument("--wait-pid", type=int, default=0, help="运行安装器前等待此进程退出")
    parser.add_argument(
        "--revision-authorization",
        default="",
        help="本地用户确认回退或重装后生成的一次性授权文件",
    )
    parser.add_argument(
        "--complete-install",
        action="store_true",
        help="由 Inno 安装成功后调用，消费重启交接文件",
    )
    parser.add_argument("--restart-handoff", default="", help="安装后重启交接 JSON 路径")
    return parser


def _load_verified_asset(
    *,
    manifest_path: str | Path,
    signature_path: str | Path,
    expected_version: str,
    expected_revision: int = 0,
    os_name: str | None = None,
    arch: str | None = None,
) -> UpdateAsset:
    """在独立辅助进程内重新建立已签名元数据的信任。"""

    manifest = UpdateManifestVerifier(public_key_pem=UPDATE_PUBLIC_KEY_PEM).load_verified(
        Path(manifest_path),
        Path(signature_path),
    )
    expected_identity = ReleaseIdentity(expected_version, expected_revision)
    if manifest.identity != expected_identity:
        raise VerificationError(
            "signed manifest release identity "
            f"{manifest.identity.tag} does not match requested version/release identity "
            f"{expected_identity.tag}"
        )
    return AssetSelector(os_name=os_name, arch=arch).select(manifest)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _consume_revision_authorization(
    *,
    authorization_path: str | Path,
    token: str,
    manifest_path: str | Path,
    target_identity: ReleaseIdentity,
    now: float | None = None,
) -> None:
    """校验并销毁与清单摘要绑定的一次性本地回退授权。"""

    authorization = Path(authorization_path).resolve()
    manifest = Path(manifest_path).resolve()
    try:
        if (
            not authorization.name.startswith(".ucrawl-revision-auth-")
            or authorization.suffix != ".json"
            or authorization.is_symlink()
            or not authorization.is_file()
            or authorization.stat().st_size > 16 * 1024
        ):
            raise VerificationError("revision authorization is missing or invalid")
        payload = json.loads(authorization.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            raise VerificationError("revision authorization payload is invalid")
        payload_identity = ReleaseIdentity(
            str(payload.get("targetVersion") or ""),
            payload.get("targetRevision"),
        )
        if (
            payload_identity != target_identity
            or str(payload.get("targetTag") or "") != target_identity.tag
        ):
            raise VerificationError("revision authorization target does not match")
        issued_at = payload.get("issuedAt")
        expires_at = payload.get("expiresAt")
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= issued_at
            or expires_at - issued_at > REVISION_AUTH_TTL_SECONDS
        ):
            raise VerificationError("revision authorization lifetime is invalid")
        current_time = int(time.time() if now is None else now)
        if issued_at > current_time + 60 or expires_at < current_time:
            raise VerificationError("revision authorization has expired")
        token_digest = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
        if not token or not hmac.compare_digest(
            token_digest,
            str(payload.get("tokenSha256") or ""),
        ):
            raise VerificationError("revision authorization token does not match")
        if not manifest.is_file() or not hmac.compare_digest(
            _sha256_path(manifest),
            str(payload.get("manifestSha256") or ""),
        ):
            raise VerificationError("revision authorization manifest does not match")
    except VerificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError("revision authorization is missing or invalid") from exc
    finally:
        authorization.unlink(missing_ok=True)


def _authorize_release_transition(
    *,
    current_identity: ReleaseIdentity,
    target_identity: ReleaseIdentity,
    manifest_path: str | Path,
    authorization_path: str | Path | None,
    token: str,
) -> None:
    """升级无需额外授权；重装和回退必须消费当前会话生成的授权。"""

    if target_identity > current_identity:
        if authorization_path or token:
            if authorization_path:
                Path(authorization_path).unlink(missing_ok=True)
            raise VerificationError("revision authorization is not valid for an upgrade")
        return
    if not authorization_path or not token:
        raise VerificationError(
            "revision reinstall or downgrade requires one-time local authorization"
        )
    _consume_revision_authorization(
        authorization_path=authorization_path,
        token=token,
        manifest_path=manifest_path,
        target_identity=target_identity,
    )


def _load_restart_argv(value: str) -> list[str]:
    if not str(value or "").strip():
        return []
    payload = json.loads(value)
    if not isinstance(payload, list) or not payload or not all(isinstance(item, str) and item for item in payload):
        raise ValueError("restart argv must be a non-empty string array")
    return payload


def _require_install_arguments(args: argparse.Namespace) -> None:
    missing = [
        option
        for option, value in (
            ("--installer", args.installer),
            ("--manifest", args.manifest),
            ("--signature", args.signature),
            ("--version", args.version),
            ("--log-path", args.log_path),
            ("--install-dir", args.install_dir),
        )
        if not str(value or "").strip()
    ]
    if missing:
        raise ValueError(f"missing updater helper arguments: {', '.join(missing)}")


def _resolve_install_dir(value: str | Path) -> Path:
    install_dir = Path(value).expanduser().resolve()
    if not install_dir.is_dir():
        raise ValueError("update install directory does not exist")
    return install_dir


def _validate_restart_argv(argv: list[str], install_dir: Path) -> list[str]:
    """只允许重启当前安装目录下的正式窗口入口，拒绝任意程序交接。"""

    if not argv:
        return []
    executable = Path(argv[0])
    if not executable.is_absolute():
        executable = install_dir / executable
    executable = executable.resolve()
    if executable.parent != install_dir.resolve():
        raise ValueError("restart executable must be inside the current install directory")
    if executable.name.casefold() not in _ALLOWED_RESTART_EXECUTABLES:
        raise ValueError("restart executable is not an approved UCrawl entry")
    if not executable.is_file():
        raise ValueError("restart executable does not exist")
    return [str(executable), *argv[1:]]


def _write_restart_handoff(
    *,
    restart_argv: list[str],
    install_dir: Path,
    version: str,
    release_revision: int,
    log_path: Path,
) -> Path:
    """原子写入 Inno 安装完成后由新 helper 消费的一次性交接文件。"""

    target = log_path.with_name(
        f"updater-restart-{os.getpid()}-{time.time_ns()}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    payload = {
        "restart_argv": restart_argv,
        "install_dir": str(install_dir),
        "version": str(version),
        "release_revision": int(release_revision),
        "log_path": str(log_path),
    }
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _read_restart_handoff(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("restart handoff is missing or too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("restart handoff must be a JSON object")
    return payload


def _post_install_restart(handoff_path: Path) -> int:
    """在 Inno 已完成文件替换后，由新版本 helper 重启原入口。"""

    payload = _read_restart_handoff(handoff_path)
    if not getattr(sys, "frozen", False):
        raise RuntimeError("post-install restart requires the frozen updater helper")
    current_install_dir = Path(sys.executable).resolve().parent
    recorded_install_dir = _resolve_install_dir(str(payload.get("install_dir") or ""))
    if recorded_install_dir != current_install_dir:
        raise ValueError("restart handoff install directory does not match updater helper")
    restart_argv = _load_restart_argv(
        json.dumps(payload.get("restart_argv"), ensure_ascii=False)
    )
    restart_argv = _validate_restart_argv(restart_argv, current_install_dir)
    version = str(payload.get("version") or "")
    release_revision = int(payload.get("release_revision") or 0)
    identity = ReleaseIdentity(version, release_revision)
    process_kwargs: dict[str, object] = {
        "shell": False,
        "cwd": str(current_install_dir),
        "close_fds": True,
    }
    if os.name == "nt":
        process_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _best_effort_update_log(
        "update.install.exit",
        "installer completed and invoked post-install helper",
        version=identity.version,
        revision=identity.revision,
        exit_code=0,
    )
    subprocess.Popen(restart_argv, **process_kwargs)
    handoff_path.unlink(missing_ok=True)
    _best_effort_update_log(
        "update.install.restart",
        "restart command launched",
        version=identity.version,
        revision=identity.revision,
    )
    return 0


def _option_value(argv: list[str], option: str) -> str:
    for index, item in enumerate(argv):
        if item.startswith(f"{option}="):
            return item.split("=", 1)[1]
        if item == option and index + 1 < len(argv):
            return argv[index + 1]
    return ""


def _failure_log_path(argv: list[str]) -> Path | None:
    direct = _option_value(argv, "--log-path")
    if direct:
        return Path(direct)
    handoff = _option_value(argv, "--restart-handoff")
    if handoff:
        try:
            payload = _read_restart_handoff(Path(handoff))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        value = str(payload.get("log_path") or "")
        return Path(value) if value else None
    return None


def _record_helper_failure(argv: list[str], exc: Exception) -> None:
    _best_effort_update_log(
        "update.install.helper_failed",
        str(exc) or type(exc).__name__,
        level="ERROR",
        error_type=type(exc).__name__,
    )
    log_path = _failure_log_path(argv)
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"updater helper failed: {type(exc).__name__}: {exc}\n"
            )
            stream.write(traceback.format_exc())
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        pass


def _wait_for_process_exit(pid: int, *, timeout_seconds: float = 120.0) -> None:
    """替换安装文件前等待 GUI 进程释放占用。"""

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
        # SYNCHRONIZE：只申请等待父进程退出所需的最小权限。
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            error_code = ctypes.get_last_error()
            if error_code == 87:  # ERROR_INVALID_PARAMETER：进程已经退出。
                return
            raise OSError(error_code, "could not open parent process")
        try:
            result = kernel32.WaitForSingleObject(handle, max(0, int(timeout_seconds * 1000)))
        finally:
            kernel32.CloseHandle(handle)
        if result == 0:  # WAIT_OBJECT_0：父进程已退出。
            return
        if result == 258:  # WAIT_TIMEOUT：继续替换文件会与父进程冲突。
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


def _launch_install(args: argparse.Namespace) -> int:
    _require_install_arguments(args)
    asset = _load_verified_asset(
        manifest_path=args.manifest,
        signature_path=args.signature,
        expected_version=str(args.version),
        expected_revision=int(args.release_revision),
    )
    install_dir = _resolve_install_dir(args.install_dir)
    target_identity = ReleaseIdentity(str(args.version), int(args.release_revision))
    current_identity = load_runtime_release_identity(install_dir)
    authorization_token = os.environ.pop(REVISION_AUTH_TOKEN_ENV, "")
    _authorize_release_transition(
        current_identity=current_identity,
        target_identity=target_identity,
        manifest_path=args.manifest,
        authorization_path=str(args.revision_authorization or "") or None,
        token=authorization_token,
    )
    restart_argv = _load_restart_argv(args.restart_argv_json)
    restart_argv = _validate_restart_argv(restart_argv, install_dir)
    _wait_for_process_exit(args.wait_pid)
    verifier = PackageVerifier(
        trusted_publishers=UPDATE_TRUSTED_PUBLISHERS,
        trusted_thumbprints=UPDATE_TRUSTED_THUMBPRINTS,
        require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE,
    )
    runner = InstallerRunner(package_verifier=verifier)
    log_path = Path(args.log_path)
    restart_handoff_path = None
    if restart_argv:
        restart_handoff_path = _write_restart_handoff(
            restart_argv=restart_argv,
            install_dir=install_dir,
            version=str(args.version),
            release_revision=int(args.release_revision),
            log_path=log_path,
        )
    try:
        runner.launch_verified_installer(
            Path(args.installer),
            asset,
            version=str(args.version),
            log_path=log_path,
            install_dir=install_dir,
            restart_handoff_path=restart_handoff_path,
        )
    except Exception:
        if restart_handoff_path is not None:
            restart_handoff_path.unlink(missing_ok=True)
        raise
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    try:
        args = build_parser().parse_args(raw_argv)
        if args.complete_install:
            if not str(args.restart_handoff or "").strip():
                raise ValueError("--restart-handoff is required with --complete-install")
            return _post_install_restart(Path(args.restart_handoff))
        return _launch_install(args)
    except Exception as exc:
        _record_helper_failure(raw_argv, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
