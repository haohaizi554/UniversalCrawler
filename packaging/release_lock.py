"""Cross-process coordination shared by the release orchestrator and leaf builds."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


LOCK_TOKEN_ENV = "UCRAWL_RELEASE_LOCK_TOKEN"
LOCK_ROOT_ENV = "UCRAWL_RELEASE_LOCK_ROOT"


def release_lock_path(project_root: Path) -> Path:
    identity = str(Path(project_root).resolve()).casefold().encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"ucrawl-release-{digest}.lock"


@contextmanager
def release_build_lock(
    project_root: Path,
    *,
    lock_path: Path | None = None,
) -> Iterator[str]:
    """Acquire the checkout lock and expose a child-only delegation token."""

    path = Path(lock_path) if lock_path is not None else release_lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    token = secrets.token_hex(32)
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                flock = getattr(fcntl, "flock")
                flock(
                    handle.fileno(),
                    getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"),
                )
        except OSError as exc:
            raise SystemExit(
                "另一个 release/build-only/leaf 构建正在占用本项目的 dist，拒绝并发构建。"
            ) from exc
        acquired = True
        handle.seek(1)
        handle.truncate(1)
        handle.write(token.encode("ascii"))
        handle.flush()
        yield token
    finally:
        if acquired:
            try:
                handle.seek(1)
                handle.truncate(1)
                handle.flush()
            except OSError:
                pass
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl = importlib.import_module("fcntl")
                    getattr(fcntl, "flock")(
                        handle.fileno(),
                        getattr(fcntl, "LOCK_UN"),
                    )
            except OSError:
                pass
        handle.close()


def _validate_parent_token(token: str, lock_root: Path) -> None:
    path = release_lock_path(lock_root)
    try:
        with path.open("rb") as handle:
            handle.seek(1)
            recorded = handle.read().decode("ascii")
    except (OSError, UnicodeError) as exc:
        raise SystemExit("父 release 构建锁不可验证，拒绝启动 leaf build。") from exc
    if not recorded or not hmac.compare_digest(recorded, token):
        raise SystemExit("父 release 构建锁 token 无效，拒绝启动 leaf build。")


@contextmanager
def leaf_build_guard(project_root: Path) -> Iterator[None]:
    """Reuse an orchestrator lock token, otherwise acquire the checkout lock directly."""

    token = str(os.environ.get(LOCK_TOKEN_ENV) or "").strip()
    raw_lock_root = str(os.environ.get(LOCK_ROOT_ENV) or "").strip()
    if token or raw_lock_root:
        if not token or not raw_lock_root:
            raise SystemExit("release 构建锁 token/root 不完整，拒绝启动 leaf build。")
        _validate_parent_token(token, Path(raw_lock_root).resolve())
        yield
        return
    with release_build_lock(Path(project_root).resolve()):
        yield
