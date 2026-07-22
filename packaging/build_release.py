"""构建可发布安装包，并原子准备热更新必需的三项资产。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from collections.abc import Mapping
from typing import Iterator

from Crypto.PublicKey import ECC

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGING_DIR = PROJECT_ROOT / "packaging"
UPDATE_TRUST_CONFIG = PROJECT_ROOT / "app" / "config" / "update_trust.py"
UPDATE_MANIFEST_TOOL = PROJECT_ROOT / "packaging" / "update_manifest.py"
RELEASE_ASSETS_ROOT = PROJECT_ROOT / "dist" / "release-assets"
DEFAULT_RELEASE_REPOSITORY = "haohaizi554/UniversalCrawler"
WINDOWS_RELEASE_TOOLS = ("N_m3u8DL-RE.exe", "ffmpeg.exe", "ffprobe.exe")
MIN_WINDOWS_TOOL_BYTES = 1024 * 1024
RELEASE_TEMP_ROOT_ENV = "UCRAWL_RELEASE_TEMP_ROOT"
USER_DATA_ROOT_ENV = "UCRAWL_USER_DATA_ROOT"
RELEASE_SMOKE_TIMEOUT_SECONDS = 60

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

from scripts.update_bootstrap import (  # noqa: E402
    DEFAULT_PRIVATE_KEY_NAME,
    DEFAULT_PUBLIC_KEY_NAME,
    begin_manifest_key_transaction,
    default_manifest_private_key_path,
    ensure_manifest_public_key,
    release_secrets_dir,
)
from release_lock import (  # noqa: E402
    LOCK_ROOT_ENV,
    LOCK_TOKEN_ENV,
    release_build_lock,
    release_lock_path,
)
from release_tool.events import ReleaseEventEmitter  # noqa: E402
from release_tool.models import (  # noqa: E402
    BuildRequest,
    ReleaseMode,
    ReleaseStage,
    RemoteReleaseInfo,
)
from release_tool.modes import resolve_release_mode  # noqa: E402
from release_tool.proxy import ProxySelection, build_proxy_environment  # noqa: E402
from release_tool.publisher import GitHubReleasePublisher  # noqa: E402
from release_tool.runner import (  # noqa: E402
    CancellationToken,
    ReleasePipelineHooks,
    SigningMaterial,
    load_request_file,
    run_release_request,
)
from release_tool.versioning import (  # noqa: E402
    apply_version_update,
    format_release_tag,
    normalize_version,
    plan_version_update,
    read_project_version,
)
from shared.release_identity import ReleaseIdentity  # noqa: E402


def _run_build(
    script_name: str,
    project_root: Path = PROJECT_ROOT,
    *,
    lock_token: str,
    lock_root: Path,
    release_identity: ReleaseIdentity | None = None,
    source_commit: str = "",
) -> None:
    root = Path(project_root).resolve()
    if release_identity is None:
        version_root = root if (root / "shared" / "version.py").is_file() else PROJECT_ROOT
        release_identity = ReleaseIdentity(read_project_version(version_root), 0)
    script = root / "packaging" / script_name
    environment = os.environ.copy()
    environment[LOCK_TOKEN_ENV] = str(lock_token)
    environment[LOCK_ROOT_ENV] = str(Path(lock_root).resolve())
    # PyInstaller imports selected modules while analyzing the graph. Isolate any
    # import-time runtime state below build/ so a release never mutates its
    # immutable sourceCommit snapshot or captures a developer's user data.
    environment[USER_DATA_ROOT_ENV] = str(root / "build" / "runtime-user-data")
    environment["UCRAWL_RELEASE_REVISION"] = str(release_identity.revision)
    environment["UCRAWL_RELEASE_TAG"] = release_identity.tag
    environment["UCRAWL_SOURCE_COMMIT"] = str(source_commit or "").strip().lower()
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--project-root",
            str(root),
        ],
        cwd=root,
        check=True,
        shell=False,
        env=environment,
    )


def _run_manifest_tool(argv: list[str], *, project_root: Path) -> None:
    root = Path(project_root).resolve()
    tool = root / "packaging" / "update_manifest.py"
    try:
        subprocess.run(
            [sys.executable, str(tool), *argv],
            cwd=root,
            check=True,
            shell=False,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"manifest tool failed with status {error.returncode}"
        ) from None
    except OSError:
        raise RuntimeError("manifest tool could not start") from None


def _run_git(argv: list[str]) -> str:
    completed = subprocess.run(
        ["git", *argv],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return completed.stdout.strip()


def _default_private_key_path() -> Path:
    return default_manifest_private_key_path(project_root=PROJECT_ROOT)


def _project_release_metadata(
    project_root: Path = PROJECT_ROOT,
    release_revision: int = 0,
) -> tuple[str, Path]:
    root = Path(project_root).resolve()
    values = runpy.run_path(str(root / "packaging" / "project_meta.py"))
    version = str(values["PACKAGE_VERSION"])
    identity = ReleaseIdentity(version, release_revision)
    installer_basename = str(values["INSTALLER_BASENAME"])
    if identity.revision:
        installer_basename += f"-r{identity.revision}"
    installer = (
        root
        / "dist"
        / "installer"
        / f"{installer_basename}.exe"
    )
    return version, installer


def _release_lock_path(project_root: Path) -> Path:
    """Return a stable, untracked lock path for one checkout's build outputs."""

    return release_lock_path(project_root)


@contextmanager
def _release_build_lock(project_root: Path) -> Iterator[str]:
    """Fail closed when another process owns this checkout's release build lock."""

    with release_build_lock(
        project_root,
        lock_path=_release_lock_path(project_root),
    ) as token:
        yield token


def _extract_source_archive(archive_path: Path, destination: Path) -> None:
    """Extract regular git archive entries without accepting links or traversal."""

    root = Path(destination).resolve()
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise SystemExit(f"git archive 包含不安全路径：{member.name}")
            target = root.joinpath(*relative.parts)
            try:
                target.resolve().relative_to(root)
            except ValueError as exc:
                raise SystemExit(f"git archive 路径越界：{member.name}") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise SystemExit(f"git archive 包含不支持的链接或特殊文件：{member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"无法读取 git archive 文件：{member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            try:
                target.chmod(member.mode & 0o777)
            except OSError:
                pass


def _load_git_lfs_entries(
    source_commit: str,
    *,
    repository_root: Path,
) -> dict[str, tuple[str, int]]:
    """Read the exact LFS OID/size contract for one source tree."""

    repository = Path(repository_root).resolve()
    try:
        completed = subprocess.run(
            ["git", "lfs", "ls-files", "--json", source_commit],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit("无法读取 Git LFS 元数据，拒绝创建发布快照。") from exc
    if payload is None or payload == []:
        return {}
    files = payload.get("files") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and files is None:
        return {}
    if not isinstance(files, list):
        raise SystemExit("Git LFS 元数据格式无效，拒绝创建发布快照。")
    entries: dict[str, tuple[str, int]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise SystemExit("Git LFS 元数据包含无效条目。")
        raw_name = str(item.get("name") or "").replace("\\", "/")
        relative = PurePosixPath(raw_name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise SystemExit(f"Git LFS 元数据包含不安全路径：{raw_name}")
        oid = str(item.get("oid") or "").strip().lower()
        raw_size = item.get("size")
        if isinstance(raw_size, bool) or not isinstance(raw_size, (int, str)):
            raise SystemExit(f"Git LFS size 无效：{raw_name}")
        try:
            size = int(raw_size)
        except ValueError as exc:
            raise SystemExit(f"Git LFS size 无效：{raw_name}") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", oid) or size < 0:
            raise SystemExit(f"Git LFS OID/size 无效：{raw_name}")
        entries[relative.as_posix()] = (oid, size)
    return entries


def _parse_lfs_pointer(path: Path) -> tuple[str, int] | None:
    candidate = Path(path)
    try:
        if candidate.stat().st_size > 1024:
            return None
        text = candidate.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    match = re.fullmatch(
        r"version https://git-lfs.github.com/spec/v1\r?\n"
        r"oid sha256:([0-9a-f]{64})\r?\n"
        r"size ([0-9]+)\r?\n?",
        text,
    )
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def _validate_materialized_lfs_file(
    path: Path,
    *,
    expected_oid: str,
    expected_size: int,
) -> None:
    candidate = Path(path)
    actual_size = candidate.stat().st_size if candidate.is_file() else -1
    if actual_size != int(expected_size):
        raise SystemExit(
            f"Git LFS 文件大小不一致：{candidate} "
            f"expected={expected_size}, actual={actual_size}"
        )
    actual_oid = _sha256_file(candidate)
    if actual_oid.lower() != str(expected_oid).lower():
        raise SystemExit(
            f"Git LFS 文件 SHA-256/OID 不一致：{candidate} "
            f"expected={expected_oid}, actual={actual_oid}"
        )


def _materialize_snapshot_lfs(
    snapshot_root: Path,
    *,
    source_commit: str,
    repository_root: Path,
) -> None:
    root = Path(snapshot_root).resolve()
    repository = Path(repository_root).resolve()
    entries = _load_git_lfs_entries(
        source_commit,
        repository_root=repository,
    )
    for relative_name, (expected_oid, expected_size) in entries.items():
        relative = PurePosixPath(relative_name)
        target = root.joinpath(*relative.parts)
        try:
            target.resolve().relative_to(root)
        except ValueError as exc:
            raise SystemExit(f"Git LFS 路径越界：{relative_name}") from exc
        if target.is_file() and target.stat().st_size == expected_size:
            if _sha256_file(target) == expected_oid:
                continue
        pointer = _parse_lfs_pointer(target)
        if pointer != (expected_oid, expected_size):
            raise SystemExit(
                f"Git archive 中的 LFS 内容既不是合法 pointer 也不匹配 OID：{relative_name}"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".lfs-materializing",
            dir=target.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        environment = os.environ.copy()
        environment.pop("GIT_LFS_SKIP_SMUDGE", None)
        environment.pop("GIT_LFS_SKIP_DOWNLOAD_ERRORS", None)
        try:
            with temporary.open("wb") as output:
                completed = subprocess.run(
                    ["git", "lfs", "smudge", relative_name],
                    cwd=repository,
                    input=target.read_bytes(),
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                    shell=False,
                    env=environment,
                )
            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise SystemExit(
                    f"无法 materialize Git LFS 文件 {relative_name}: {detail}"
                )
            _validate_materialized_lfs_file(
                temporary,
                expected_oid=expected_oid,
                expected_size=expected_size,
            )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    for candidate in root.rglob("*"):
        if candidate.is_file() and _parse_lfs_pointer(candidate) is not None:
            relative_name = candidate.relative_to(root).as_posix()
            if relative_name not in entries:
                raise SystemExit(
                    f"Git archive 遗留未声明的 LFS pointer，拒绝构建：{relative_name}"
                )


def _validate_windows_release_tools(project_root: Path) -> None:
    root = Path(project_root).resolve()
    for name in WINDOWS_RELEASE_TOOLS:
        tool = root / name
        if not tool.is_file():
            raise SystemExit(f"发布快照缺少 Windows 运行工具：{tool}")
        size = tool.stat().st_size
        if size < MIN_WINDOWS_TOOL_BYTES:
            raise SystemExit(f"Windows 运行工具大小过小，疑似 LFS pointer：{tool} ({size})")
        with tool.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise SystemExit(f"Windows 运行工具不是有效 PE/MZ 文件：{tool}")


def _release_snapshot_temp_root(repository: Path) -> Path:
    """Return a short build root so deep bundled assets stay below Win32 path limits."""

    configured = str(os.environ.get(RELEASE_TEMP_ROOT_ENV) or "").strip()
    root = (
        Path(configured).expanduser()
        if configured
        else Path(repository).resolve().parent / ".ucrawl-release-tmp"
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"无法创建发布临时目录：{root}") from exc
    if not root.is_dir():
        raise SystemExit(f"发布临时目录不是文件夹：{root}")
    return root.resolve()


@contextmanager
def _source_snapshot(
    source_commit: str,
    *,
    repository_root: Path = PROJECT_ROOT,
) -> Iterator[Path]:
    """Yield a temporary immutable source tree exported from ``source_commit``."""

    commit = str(source_commit).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"无法为无效 source commit 创建快照：{source_commit}")
    repository = Path(repository_root).resolve()
    temporary_parent = _release_snapshot_temp_root(repository)
    # Inno Setup still encounters legacy Win32 path limits while walking bundled
    # browser assets. Keep both generated names deliberately short.
    with tempfile.TemporaryDirectory(prefix="r-", dir=temporary_parent) as temp_dir:
        temporary_root = Path(temp_dir)
        archive_path = temporary_root / "s.tar"
        snapshot_root = temporary_root / "p"
        snapshot_root.mkdir()
        try:
            subprocess.run(
                [
                    "git",
                    "archive",
                    "--format=tar",
                    f"--output={archive_path}",
                    commit,
                ],
                cwd=repository,
                check=True,
                capture_output=True,
                shell=False,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(f"无法从 source commit {commit} 创建构建快照") from exc
        _extract_source_archive(archive_path, snapshot_root)
        archive_path.unlink(missing_ok=True)
        _materialize_snapshot_lfs(
            snapshot_root,
            source_commit=commit,
            repository_root=repository,
        )
        yield snapshot_root


def _validate_release_identity(
    *,
    package_version: str,
    version: str,
    release_revision: int = 0,
    tag: str,
) -> None:
    package_text = str(package_version).strip()
    version_text = str(version).strip()
    normalized_tag = str(tag).strip()
    try:
        normalized_package = normalize_version(package_text)
        normalized_version = normalize_version(version_text)
    except ValueError as exc:
        raise SystemExit(f"release version is invalid: {exc}") from exc
    if package_text != normalized_package:
        raise SystemExit(
            "canonical package version must not include a v prefix: "
            f"{package_text!r}"
        )
    if normalized_version != normalized_package:
        raise SystemExit(
            "发布版本与实际构建包版本不一致："
            f"package={normalized_package}, release={normalized_version}。"
        )
    try:
        expected_tag = format_release_tag(normalized_version, release_revision)
    except ValueError as exc:
        raise SystemExit(f"release revision is invalid: {exc}") from exc
    if normalized_tag != expected_tag:
        raise SystemExit(
            f"release tag 必须与版本完全一致：expected={expected_tag}, actual={normalized_tag}。"
        )
    if not re.fullmatch(r"v[0-9A-Za-z][0-9A-Za-z._-]*", normalized_tag):
        raise SystemExit(f"release tag 格式无效：{normalized_tag}")


def _validate_private_key_path(private_key: Path) -> Path:
    resolved = Path(private_key).expanduser().resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("manifest private key must not be inside the Git working tree")
    if not resolved.is_file():
        raise SystemExit(
            "未找到 update manifest 私钥，请先运行："
            "python scripts/update_bootstrap.py generate-manifest-key"
        )
    resolved = _require_readable_regular_file(resolved, label="manifest private key")
    try:
        key = ECC.import_key(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, IndexError, TypeError):
        raise ValueError("manifest private key is invalid") from None
    if not key.has_private() or key.curve != "Ed25519":
        raise ValueError("manifest private key is invalid")
    return resolved


def _read_only_secret_path(filename: str) -> Path:
    return release_secrets_dir(project_root=PROJECT_ROOT, create=False) / filename


def _read_only_public_key_path() -> Path:
    return _read_only_secret_path(DEFAULT_PUBLIC_KEY_NAME)


def _require_readable_regular_file(path: Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise ValueError(f"{label} is unavailable")
    try:
        with resolved.open("rb") as handle:
            if not handle.read(1):
                raise ValueError(f"{label} is unavailable")
    except OSError as error:
        raise ValueError(f"{label} is unavailable") from error
    return resolved


def _validate_public_key_path(public_key: Path) -> Path:
    resolved = _require_readable_regular_file(public_key, label="manifest public key")
    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("manifest public key is unavailable") from error
    if "BEGIN PUBLIC KEY" not in content or "PRIVATE KEY" in content:
        raise ValueError("manifest public key is invalid")
    return resolved


def _manifest_public_key_from_private(private_key: Path) -> tuple[str, str]:
    try:
        key = ECC.import_key(Path(private_key).read_text(encoding="utf-8"))
        public_pem = key.public_key().export_key(format="PEM")
    except (OSError, UnicodeError, ValueError, IndexError, TypeError):
        raise ValueError("manifest private key is invalid") from None
    fingerprint = hashlib.sha256(public_pem.encode("utf-8")).hexdigest().upper()
    return public_pem.strip(), fingerprint


def _manifest_public_key_fingerprint(public_key: Path) -> tuple[str, str]:
    resolved = _validate_public_key_path(public_key)
    try:
        public_pem = ECC.import_key(
            resolved.read_text(encoding="utf-8")
        ).export_key(format="PEM")
    except (OSError, UnicodeError, ValueError, IndexError, TypeError):
        raise ValueError("manifest public key is invalid") from None
    fingerprint = hashlib.sha256(public_pem.encode("utf-8")).hexdigest().upper()
    return public_pem.strip(), fingerprint


def _relative_release_paths(paths: tuple[Path, ...]) -> tuple[str, ...]:
    root = PROJECT_ROOT.resolve()
    relative_paths: list[str] = []
    for path in paths:
        try:
            relative = Path(path).resolve().relative_to(root).as_posix()
        except ValueError as error:
            raise SystemExit("version update includes a path outside the repository") from error
        relative_paths.append(relative)
    return tuple(sorted(set(relative_paths)))


def _git_path_set(argv: list[str]) -> set[str]:
    output = _run_git(argv)
    return {line.replace("\\", "/") for line in output.splitlines() if line.strip()}


def _validate_release_baseline_clean() -> None:
    if _run_git(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise SystemExit("formal release requires a clean Git worktree and index")


def _new_release_requires_clean_baseline(request: BuildRequest) -> bool:
    return any(
        getattr(request, field)
        for field in (
            "apply_version",
            "build_portable",
            "build_installer",
            "commit_version_changes",
            "push_main",
            "create_or_reuse_tag",
        )
    )


def _validate_version_commit(paths: tuple[str, ...], commit: str) -> None:
    expected = set(paths)
    committed = _git_path_set(["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
    if committed != expected:
        raise SystemExit("release version commit includes unexpected files")
    _validate_release_baseline_clean()


def _validate_repository(repository: str) -> str:
    normalized = str(repository or "").strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized):
        raise SystemExit(f"GitHub repository 格式无效：{repository}")
    return normalized


def _validate_git_release_state(tag: str) -> str:
    """正式资产只能来自干净、且由同名 tag 精确指向的 HEAD。"""

    try:
        status = _run_git(["status", "--porcelain", "--untracked-files=all"])
        head = _run_git(["rev-parse", "HEAD"])
        tag_commit = _run_git(["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            f"无法验证 release tag {tag}；请先提交全部源码并让 tag 指向当前 HEAD。"
        ) from exc
    if status:
        preview = "\n".join(status.splitlines()[:12])
        raise SystemExit(f"Git 工作树存在未提交改动，拒绝构建正式发布资产：\n{preview}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head):
        raise SystemExit(f"无法解析当前 HEAD commit：{head}")
    if tag_commit.lower() != head.lower():
        raise SystemExit(
            f"同版本修复要求 release tag {tag} 精确指向当前 HEAD；"
            "当前源码已偏离该发布。请改用本地构建，或提高版本号后正式发布。"
            f"tag={tag_commit}, HEAD={head}"
        )
    return head.lower()


def _git_tag_exists(tag: str) -> bool:
    """只判断本地 tag 是否存在；新修订 tag 允许在发布流程后续创建。"""

    try:
        _run_git(["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _validate_final_publish_window(tag: str, source_commit: str) -> None:
    """在原子发布前重验 live tag/HEAD，禁止 staging 使用过期源码身份。"""

    live_commit = _validate_git_release_state(tag)
    if live_commit != source_commit:
        raise SystemExit(
            "最终发布窗口的 tag/HEAD 源提交已变化，拒绝发布："
            f"expected={source_commit}, actual={live_commit}"
        )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_staged_manifest(
    manifest_path: Path,
    signature_path: Path,
    *,
    project_root: Path,
) -> None:
    """对最终 staging bytes 再走一次客户端同款验签和 schema 校验。"""

    root = Path(project_root).resolve()
    verifier = (
        "import sys\n"
        "from pathlib import Path\n"
        "root = Path(sys.argv[1]).resolve()\n"
        "sys.path.insert(0, str(root))\n"
        "from app.config.update_trust import UPDATE_PUBLIC_KEY_PEM\n"
        "from app.services.secure_updater import UpdateManifestVerifier\n"
        "UpdateManifestVerifier(public_key_pem=UPDATE_PUBLIC_KEY_PEM).load_verified("
        "Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            verifier,
            str(root),
            str(Path(manifest_path).resolve()),
            str(Path(signature_path).resolve()),
        ],
        cwd=root,
        check=True,
        shell=False,
    )


def _validate_staged_assets(
    staging: Path,
    *,
    installer_name: str,
    installer_size: int,
    installer_sha256: str,
    asset_url: str,
    version: str,
    release_revision: int = 0,
    tag: str,
    source_commit: str,
    project_root: Path,
) -> None:
    required_names = {installer_name, "latest.json", "latest.json.sig"}
    entries = list(staging.iterdir())
    actual_names = {path.name for path in entries}
    if actual_names != required_names or any(not path.is_file() for path in entries):
        raise RuntimeError(
            "热更新发布目录必须且只能包含安装包、latest.json、latest.json.sig："
            f"expected={sorted(required_names)}, actual={sorted(actual_names)}"
        )
    installer = staging / installer_name
    manifest = staging / "latest.json"
    signature = staging / "latest.json.sig"
    if not signature.read_bytes():
        raise RuntimeError("latest.json.sig 为空，拒绝发布")
    _verify_staged_manifest(
        manifest,
        signature,
        project_root=project_root,
    )
    actual_sha256 = _sha256_file(installer)
    if actual_sha256 != installer_sha256:
        raise RuntimeError("最终 staging 安装包 SHA-256 在发布校验期间发生变化")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("schema") != 1:
        raise RuntimeError("latest.json schema 必须为 1")
    if payload.get("version") != version or payload.get("tag") != tag:
        raise RuntimeError("latest.json 的 version/tag 与本次发布不一致")
    if payload.get("releaseRevision") != release_revision:
        raise RuntimeError("latest.json 的 releaseRevision 与本次发布不一致")
    if payload.get("sourceCommit") != source_commit:
        raise RuntimeError("latest.json 的 sourceCommit 与 release tag commit 不一致")
    assets = payload.get("assets")
    if not isinstance(assets, dict) or set(assets) != {"windows-x64"}:
        raise RuntimeError("latest.json 必须且只能声明 windows-x64 资产")
    asset = assets["windows-x64"]
    expected = {
        "name": installer_name,
        "url": asset_url,
        "sha256": actual_sha256,
        "size": installer_size,
        "installerType": "inno",
        "os": "windows",
        "arch": "x64",
    }
    actual = {key: asset.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            "latest.json 的 Windows 安装包元数据与最终文件不一致："
            f"expected={expected}, actual={actual}"
        )


def _prepare_release_assets(
    *,
    installer: Path,
    private_key: Path,
    version: str,
    release_revision: int = 0,
    tag: str,
    source_commit: str,
    repository: str,
    output_root: Path = RELEASE_ASSETS_ROOT,
    notes: str = "",
    project_root: Path,
) -> Path:
    """在临时目录完成签名与回验，成功后一次性发布三项本地资产。"""

    source_installer = Path(installer).resolve()
    if not source_installer.is_file():
        raise SystemExit(f"安装包构建失败，未找到输出文件：{source_installer}")
    key_path = _validate_private_key_path(private_key)
    repo = _validate_repository(repository)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / tag
    if destination.exists():
        raise SystemExit(
            f"发布资产目录已存在，拒绝覆盖：{destination}。请人工核验并移走旧目录后重试。"
        )

    staging = Path(tempfile.mkdtemp(prefix=f".{tag}-", dir=root))
    try:
        staged_installer = staging / source_installer.name
        shutil.copy2(source_installer, staged_installer)
        asset_url = (
            f"https://github.com/{repo}/releases/download/"
            f"{tag}/{staged_installer.name}"
        )
        asset_spec = staging / ".asset-spec.json"
        asset_spec.write_text(
            json.dumps(
                [
                    {
                        "key": "windows-x64",
                        "path": str(staged_installer),
                        "url": asset_url,
                        "os": "windows",
                        "arch": "x64",
                        "installerType": "inno",
                    }
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _run_manifest_tool(
            [
                "--output-dir",
                str(staging),
                "--private-key",
                str(key_path),
                "--version",
                version,
                "--release-revision",
                str(release_revision),
                "--tag",
                tag,
                "--asset-spec",
                str(asset_spec),
                "--notes",
                notes,
                "--source-commit",
                source_commit,
            ],
            project_root=project_root,
        )
        asset_spec.unlink(missing_ok=True)
        installer_sha256 = _sha256_file(staged_installer)
        _validate_staged_assets(
            staging,
            installer_name=staged_installer.name,
            installer_size=staged_installer.stat().st_size,
            installer_sha256=installer_sha256,
            asset_url=asset_url,
            version=version,
            release_revision=release_revision,
            tag=tag,
            source_commit=source_commit,
            project_root=project_root,
        )
        _validate_final_publish_window(tag, source_commit)
        staging.replace(destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _trust_values(values: dict[str, object], key: str) -> tuple[str, ...]:
    raw_values = values.get(key, ())
    if not isinstance(raw_values, (list, tuple)):
        raise SystemExit(f"生产更新信任配置 {key} 格式无效。")
    return tuple(str(value) for value in raw_values if str(value))


def _validate_production_trust(
    *,
    config_path: Path = UPDATE_TRUST_CONFIG,
) -> dict[str, object]:
    """公开信任配置不完整时在冻结生产客户端前失败，避免产出无法验证更新的版本。"""

    values = runpy.run_path(str(config_path))
    public_key = str(values.get("UPDATE_PUBLIC_KEY_PEM") or "")
    publishers = _trust_values(values, "UPDATE_TRUSTED_PUBLISHERS")
    thumbprints = _trust_values(values, "UPDATE_TRUSTED_THUMBPRINTS")
    require_os_signature = values.get("UPDATE_REQUIRE_OS_SIGNATURE") is True
    if "BEGIN PUBLIC KEY" not in public_key or "PRIVATE KEY" in public_key:
        raise SystemExit("生产更新公钥未配置或格式无效，拒绝构建签名 Release。")
    if not require_os_signature:
        raise SystemExit("签名 Release 必须设置 UPDATE_REQUIRE_OS_SIGNATURE=True。")
    if not publishers:
        raise SystemExit("生产更新发布者未配置，拒绝构建签名 Release。")
    if not thumbprints:
        raise SystemExit("生产更新证书指纹未配置，拒绝构建签名 Release。")
    return values


def _snapshot_source_fingerprints(project_root: Path) -> dict[str, str]:
    root = Path(project_root).resolve()
    fingerprints: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in {".git", "build", "dist"}:
            continue
        if "__pycache__" in relative.parts or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        fingerprints[relative.as_posix()] = _sha256_file(path)
    return fingerprints


def _validate_snapshot_source_unchanged(
    project_root: Path,
    expected: dict[str, str],
) -> None:
    root = Path(project_root).resolve()
    actual = _snapshot_source_fingerprints(root)
    changed = sorted(
        relative_name
        for relative_name in expected.keys() | actual.keys()
        if expected.get(relative_name) != actual.get(relative_name)
    )
    if changed:
        preview = ", ".join(changed[:8])
        raise SystemExit(
            "构建过程修改、新增或删除了 sourceCommit 快照源码，拒绝发布："
            f"{preview}"
        )


def _extract_windows_trust(installer: Path, *, project_root: Path) -> dict[str, object]:
    root = Path(project_root).resolve()
    bootstrap = root / "scripts" / "update_bootstrap.py"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(bootstrap),
                "extract-windows-trust",
                "--installer",
                str(Path(installer).resolve()),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit("无法读取最终 Windows 安装器签名身份。") from exc
    if not isinstance(payload, dict):
        raise SystemExit("最终 Windows 安装器签名身份格式无效。")
    return payload


def _normalized_fingerprint(value: object) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).upper()


def _validate_windows_signer_identity(
    trust: dict[str, object],
    signer: dict[str, object],
) -> None:
    if str(signer.get("status") or "") != "Valid":
        raise SystemExit("最终 Windows installer signer 状态无效。")
    subject = str(signer.get("subject") or "")
    publishers = _trust_values(trust, "UPDATE_TRUSTED_PUBLISHERS")
    if publishers and not any(publisher in subject for publisher in publishers):
        raise SystemExit("最终 Windows installer signer publisher 不在提交内信任列表。")
    trusted_fingerprints = {
        _normalized_fingerprint(value)
        for value in _trust_values(trust, "UPDATE_TRUSTED_THUMBPRINTS")
        if _normalized_fingerprint(value)
    }
    signer_fingerprints = {
        _normalized_fingerprint(signer.get("sha1_thumbprint")),
        _normalized_fingerprint(signer.get("sha256_fingerprint")),
    }
    if not trusted_fingerprints.intersection(signer_fingerprints):
        raise SystemExit("最终 Windows installer signer 指纹不在提交内信任列表。")


def _build_binaries(
    project_root: Path = PROJECT_ROOT,
    *,
    lock_token: str,
    lock_root: Path,
    enforce_source_immutability: bool = True,
    build_portable: bool = True,
    build_installer: bool = True,
    release_revision: int = 0,
    source_commit: str = "",
) -> None:
    root = Path(project_root).resolve()
    version_root = root if (root / "shared" / "version.py").is_file() else PROJECT_ROOT
    release_identity = ReleaseIdentity(read_project_version(version_root), release_revision)
    source_fingerprints = (
        _snapshot_source_fingerprints(root) if enforce_source_immutability else {}
    )
    signed_build = build_installer and os.environ.get("UCRAWL_SIGN_WINDOWS") == "1"
    trust: dict[str, object] | None = None
    if signed_build:
        trust = _validate_production_trust(
            config_path=root / "app" / "config" / "update_trust.py"
        )
    if build_portable:
        _run_build(
            "build_portable.py",
            root,
            lock_token=lock_token,
            lock_root=lock_root,
            release_identity=release_identity,
            source_commit=source_commit,
        )
    if build_installer:
        _run_build(
            "build_installer.py",
            root,
            lock_token=lock_token,
            lock_root=lock_root,
            release_identity=release_identity,
            source_commit=source_commit,
        )
    if enforce_source_immutability:
        _validate_snapshot_source_unchanged(root, source_fingerprints)
    if signed_build and trust is not None:
        _version, installer = _project_release_metadata(root, release_revision)
        signer = _extract_windows_trust(installer, project_root=root)
        _validate_windows_signer_identity(trust, signer)


def _build_pipeline_hooks(
    request: BuildRequest,
    environment: Mapping[str, str],
    emitter: object | None,
) -> ReleasePipelineHooks:
    """Adapt the existing release primitives to one request-scoped runner."""

    resources = ExitStack()
    active_stage_lock = threading.Lock()
    state: dict[str, object] = {
        "active_progress": 0,
        "active_stage": ReleaseStage.IDLE,
        "assets": (),
        "uploaded_assets": (),
        "build_root": None,
        "child_environment": None,
        "installer": None,
        "lock_token": "",
        "publisher": None,
        "snapshot_root": None,
        "source_commit": "",
        "signing_material": None,
        "version_plan": None,
        "version_result": None,
    }
    tag = format_release_tag(request.target_version, request.release_revision)
    formal_build = (
        request.sign_manifest
        or request.upload_release_assets
        or request.create_or_update_release
        or request.rotate_trust_anchor
    )

    def activate_stage(stage: ReleaseStage, progress: int) -> None:
        with active_stage_lock:
            state["active_stage"] = stage
            state["active_progress"] = progress

    def emit_log(message: str) -> None:
        if emitter is None:
            return
        emit = getattr(emitter, "emit", None)
        if callable(emit):
            with active_stage_lock:
                stage = state["active_stage"]
                progress = state["active_progress"]
            emit("log", stage=stage, progress=progress, message=message)

    def resolve_release_context() -> tuple[dict[str, str], GitHubReleasePublisher]:
        child_environment = state["child_environment"]
        publisher = state["publisher"]
        if isinstance(child_environment, dict) and publisher is not None:
            return child_environment, publisher

        proxy_label = request.proxy_label.strip()
        proxy_label_from_environment = proxy_label.startswith("env:")
        if proxy_label_from_environment:
            proxy_label = str(environment.get(proxy_label[4:]) or "").strip()
            if not proxy_label:
                raise ValueError("proxy selection reference is unavailable")
        custom_proxy = request.custom_proxy.strip()
        custom_proxy_from_environment = custom_proxy.startswith("env:")
        if custom_proxy_from_environment:
            custom_proxy = str(environment.get(custom_proxy[4:]) or "").strip()
            if not custom_proxy:
                raise ValueError("custom proxy reference is unavailable")
        child_environment = build_proxy_environment(
            ProxySelection(
                label=proxy_label,
                endpoint=custom_proxy,
                label_from_environment=proxy_label_from_environment,
                endpoint_from_environment=custom_proxy_from_environment,
            ),
            environment,
        )
        publisher = GitHubReleasePublisher(
            request.repository,
            child_environment,
            emit_log,
            project_root=PROJECT_ROOT,
        )
        state["child_environment"] = child_environment
        state["publisher"] = publisher
        return child_environment, publisher

    def plan_version(target_version: str):
        plan = plan_version_update(target_version, PROJECT_ROOT)
        state["version_plan"] = plan
        return plan

    def apply_version(target_version: str):
        plan = plan_version(target_version)
        result = apply_version_update(plan)
        state["version_result"] = result
        return result

    def validate_dependencies(_request: BuildRequest) -> None:
        child_environment, _publisher = resolve_release_context()
        if request.release_notes_path:
            _require_readable_regular_file(Path(request.release_notes_path), label="release notes")
        if (
            request.sign_manifest or request.upload_release_assets
        ) and not request.generate_manifest_key:
            _private_key_path(request, child_environment)

    def ensure_lock() -> str:
        lock_token = state["lock_token"]
        if isinstance(lock_token, str) and lock_token:
            return lock_token
        lock_token = resources.enter_context(_release_build_lock(PROJECT_ROOT))
        state["lock_token"] = lock_token
        return lock_token

    def prepare(_request: BuildRequest, mode: ReleaseMode) -> None:
        ensure_lock()
        if formal_build or (
            mode is ReleaseMode.NEW_RELEASE
            and _new_release_requires_clean_baseline(request)
        ):
            _validate_release_baseline_clean()
        if formal_build and mode is ReleaseMode.SAME_RELEASE_REPAIR and _git_tag_exists(tag):
            # 同版本修订依赖既有 tag 绑定源码。先在 preflight 拒绝错配，
            # 避免读取私钥、生成签名或构建数 GB 资产后才发现目标不可发布。
            _validate_git_release_state(tag)

    def resolve_request_signing_material(
        _request: BuildRequest,
    ) -> SigningMaterial:
        child_environment, _publisher = resolve_release_context()
        if request.generate_manifest_key:
            existing_private = _read_only_secret_path(DEFAULT_PRIVATE_KEY_NAME)
            if not request.rotate_trust_anchor and not existing_private.is_file():
                raise ValueError(
                    "generating a new manifest key requires explicit trust anchor rotation"
                )
            transaction = begin_manifest_key_transaction(
                project_root=PROJECT_ROOT,
                rotate=request.rotate_trust_anchor,
                write_public_key_to_config=request.rotate_trust_anchor,
                config_path=UPDATE_TRUST_CONFIG,
            )
            result = transaction.result
            material = SigningMaterial(
                private_key_path=Path(result.private_key_path).resolve(),
                public_key_path=Path(result.public_key_path).resolve(),
                fingerprint=str(result.public_key_fingerprint_sha256),
                trust_anchor_changed=request.rotate_trust_anchor,
                commit_transaction=transaction.commit,
                rollback_transaction=transaction.rollback,
            )
        else:
            private_key: Path | None = None
            public_key: Path | None = None
            private_public_pem = ""
            fingerprint = ""
            if request.sign_manifest or request.upload_release_assets:
                private_key = _private_key_path(request, child_environment)
                private_public_pem, fingerprint = _manifest_public_key_from_private(
                    private_key
                )
            if request.upload_public_key:
                if private_key is None:
                    default_private = _read_only_secret_path(
                        DEFAULT_PRIVATE_KEY_NAME
                    )
                    if request.private_key_path.strip() or default_private.is_file():
                        private_key = _private_key_path(request, child_environment)
                        private_public_pem, fingerprint = (
                            _manifest_public_key_from_private(private_key)
                        )
                if private_key is not None:
                    repaired = ensure_manifest_public_key(
                        private_key_path=private_key,
                        public_key_path=_read_only_public_key_path(),
                    )
                    public_key = _validate_public_key_path(
                        repaired.public_key_path
                    )
                    public_pem, public_fingerprint = (
                        _manifest_public_key_fingerprint(public_key)
                    )
                    if public_pem != private_public_pem:
                        raise ValueError(
                            "manifest public key repair did not match the selected private key"
                        )
                    fingerprint = public_fingerprint
                else:
                    public_key = _validate_public_key_path(
                        _read_only_public_key_path()
                    )
                    _public_pem, fingerprint = (
                        _manifest_public_key_fingerprint(public_key)
                    )
            material = SigningMaterial(
                private_key_path=private_key,
                public_key_path=public_key,
                fingerprint=fingerprint,
                trust_anchor_changed=False,
            )
        state["signing_material"] = material
        filenames = [
            path.name
            for path in (material.private_key_path, material.public_key_path)
            if path is not None
        ]
        label = ", ".join(filenames) if filenames else "public trust asset"
        emit_log(
            "manifest signing material ready: "
            f"{label}; public fingerprint={material.fingerprint}"
        )
        return material

    def ensure_snapshot() -> tuple[Path, str]:
        snapshot_root = state["snapshot_root"]
        source_commit = state["source_commit"]
        if isinstance(snapshot_root, Path) and isinstance(source_commit, str) and source_commit:
            return snapshot_root, source_commit
        source_commit = _validate_git_release_state(tag)
        lock_token = ensure_lock()
        if _validate_git_release_state(tag) != source_commit:
            raise SystemExit("HEAD or release tag changed while waiting for the release build lock")
        snapshot_root = resources.enter_context(
            _source_snapshot(source_commit, repository_root=PROJECT_ROOT)
        )
        _validate_windows_release_tools(snapshot_root)
        snapshot_version, installer = _project_release_metadata(
            snapshot_root,
            request.release_revision,
        )
        _validate_release_identity(
            package_version=snapshot_version,
            version=request.target_version,
            release_revision=request.release_revision,
            tag=tag,
        )
        state["snapshot_root"] = snapshot_root
        state["build_root"] = snapshot_root
        state["source_commit"] = source_commit
        state["installer"] = installer
        state["lock_token"] = lock_token
        return snapshot_root, source_commit

    def build_selected(*, portable: bool, installer: bool) -> None:
        if not formal_build:
            lock_token = ensure_lock()
            state["build_root"] = PROJECT_ROOT
            _build_binaries(
                PROJECT_ROOT,
                lock_token=lock_token,
                lock_root=PROJECT_ROOT,
                enforce_source_immutability=False,
                build_portable=portable,
                build_installer=installer,
                release_revision=request.release_revision,
            )
            return
        snapshot_root, _source_commit = ensure_snapshot()
        lock_token = str(state["lock_token"])
        _build_binaries(
            snapshot_root,
            lock_token=lock_token,
            lock_root=PROJECT_ROOT,
            build_portable=portable,
            build_installer=installer,
            release_revision=request.release_revision,
            source_commit=_source_commit,
        )

    def sign_manifest(_request: BuildRequest) -> tuple[Path, ...]:
        _child_environment, _publisher = resolve_release_context()
        snapshot_root, source_commit = ensure_snapshot()
        installer = state["installer"]
        if not isinstance(installer, Path):
            raise RuntimeError("release installer is unavailable for manifest signing")
        material = state["signing_material"]
        if not isinstance(material, SigningMaterial) or material.private_key_path is None:
            raise RuntimeError("release signing material was not resolved before build")
        private_key = _validate_private_key_path(material.private_key_path)
        notes = _release_notes(request.release_notes_path)
        release_dir = _prepare_release_assets(
            installer=installer,
            private_key=private_key,
            version=request.target_version,
            release_revision=request.release_revision,
            tag=tag,
            source_commit=source_commit,
            repository=request.repository,
            output_root=Path(request.output_root) if request.output_root else RELEASE_ASSETS_ROOT,
            notes=notes,
            project_root=snapshot_root,
        )
        assets = tuple(sorted(release_dir.iterdir()))
        state["assets"] = assets
        return assets

    def commit_version_changes(_request: BuildRequest) -> str:
        result = state["version_result"]
        paths = list(getattr(result, "changed_files", ()))
        material = state["signing_material"]
        if isinstance(material, SigningMaterial) and material.trust_anchor_changed:
            paths.append(UPDATE_TRUST_CONFIG)
        if paths:
            relative_paths = _relative_release_paths(tuple(paths))
            if _git_path_set(["diff", "--cached", "--name-only"]) or _git_path_set(
                ["diff", "--name-only"]
            ) != set(relative_paths):
                raise SystemExit("version update has unexpected Git changes")
            _run_git(["add", "--", *relative_paths])
            if _git_path_set(["diff", "--cached", "--name-only"]) != set(relative_paths):
                raise SystemExit("version update staged unexpected Git changes")
            _run_git(
                [
                    "commit",
                    "--only",
                    "-m",
                    f"chore: release {request.target_version}",
                    "--",
                    *relative_paths,
                ]
            )
            commit = _run_git(["rev-parse", "HEAD"])
            _validate_version_commit(relative_paths, commit)
            return commit
        return _run_git(["rev-parse", "HEAD"])

    def push_main(_request: BuildRequest, commit: str) -> None:
        verified_commit = str(commit or _run_git(["rev-parse", "HEAD"])).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", verified_commit):
            raise SystemExit("release push requires a verified full commit SHA")
        _validate_release_baseline_clean()
        if _run_git(["rev-parse", "HEAD"]).lower() != verified_commit:
            raise SystemExit("HEAD changed after the release version commit was verified")
        _run_git(
            [
                "push",
                "origin",
                f"{verified_commit}:refs/heads/main",
            ]
        )
        remote_main = _run_git(
            ["ls-remote", "--exit-code", "origin", "refs/heads/main"]
        ).split()
        if not remote_main or remote_main[0].lower() != verified_commit:
            raise SystemExit("remote main does not match the verified release commit")

    def ensure_tag(_request: BuildRequest, commit: str) -> None:
        mode = resolve_release_mode(
            _request.target_version,
            _request.remote,
            same_release_repair=_request.same_release_repair,
            offline_debug=_request.offline_debug,
        )
        if mode is ReleaseMode.NEW_RELEASE:
            source_commit = str(commit or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
                raise SystemExit(
                    "new release tag requires a verified version commit"
                )
        else:
            source_commit = str(commit or _run_git(["rev-parse", "HEAD"])).strip()
        _child_environment, publisher = resolve_release_context()
        if formal_build:
            _validate_release_baseline_clean()
        try:
            existing = _run_git(["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"])
        except subprocess.CalledProcessError:
            _run_git(["tag", tag, source_commit])
        else:
            if existing.lower() != source_commit.lower():
                raise SystemExit(
                    f"不可变 release tag {tag} 已指向其他源码；"
                    "请刷新远端状态并使用下一个修订号。"
                )
        publisher.ensure_tag(tag, source_commit)

    def ensure_release(_request: BuildRequest) -> None:
        _child_environment, publisher = resolve_release_context()
        if not request.release_notes_path:
            raise ValueError("creating a release requires release_notes_path")
        publisher.ensure_release(
            tag,
            # GitHub 左侧发布列表很窄，标题直接使用规范 tag，避免产品名
            # 挤掉真正用于区分同版本修订的 ``-rN`` 后缀。
            tag,
            request.release_notes_path,
            repair=False,
        )

    def upload_assets(_request: BuildRequest, assets: tuple[Path, ...]) -> None:
        _child_environment, publisher = resolve_release_context()
        selected = list(assets or state["assets"])
        if request.upload_public_key:
            material = state["signing_material"]
            if (
                not isinstance(material, SigningMaterial)
                or material.public_key_path is None
            ):
                raise RuntimeError("release public key asset was not resolved")
            selected.append(_validate_public_key_path(material.public_key_path))
        uploaded = tuple(selected)
        state["uploaded_assets"] = uploaded
        publisher.upload_assets(tag, uploaded, repair=False)

    def verify_remote_assets(_request: BuildRequest, assets: tuple[Path, ...]) -> None:
        _child_environment, publisher = resolve_release_context()
        uploaded = state["uploaded_assets"]
        expected = uploaded if isinstance(uploaded, tuple) and uploaded else assets or state["assets"]
        publisher.verify_assets(tag, expected)

    def run_smoke_tests() -> None:
        child_environment, _publisher = resolve_release_context()
        build_root = state["build_root"]
        if not isinstance(build_root, Path):
            raise RuntimeError("portable build context is unavailable for smoke testing")
        portable_root = build_root / "dist" / "UniversalCrawlerPro"
        cli = portable_root / "UCrawlCLI.exe"
        build_info = portable_root / "BUILD_INFO.txt"
        if not cli.is_file() or not build_info.is_file():
            raise RuntimeError("portable smoke test artifacts are incomplete")
        if request.build_installer:
            _version, installer = _project_release_metadata(
                build_root,
                request.release_revision,
            )
            if not installer.is_file():
                raise RuntimeError("installer artifact is unavailable for smoke testing")
        try:
            completed = subprocess.run(
                [str(cli.resolve()), "--mode", "cli", "--help"],
                cwd=portable_root.resolve(),
                env=dict(child_environment),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=RELEASE_SMOKE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("portable CLI smoke test could not complete") from error
        if completed.returncode:
            raise RuntimeError("portable CLI smoke test failed")

    return ReleasePipelineHooks(
        plan_version=plan_version,
        apply_version=apply_version,
        resolve_signing_material=resolve_request_signing_material,
        build_portable=lambda: build_selected(portable=True, installer=False),
        build_installer=lambda: build_selected(portable=False, installer=True),
        run_smoke_tests=run_smoke_tests,
        sign_manifest=sign_manifest,
        commit_version_changes=commit_version_changes,
        push_main=push_main,
        ensure_tag=ensure_tag,
        ensure_release=ensure_release,
        upload_assets=upload_assets,
        verify_remote_assets=verify_remote_assets,
        validate_dependencies=validate_dependencies,
        prepare=prepare,
        cleanup=resources.close,
        activate_stage=activate_stage,
    )


def _private_key_path(request: BuildRequest, environment: Mapping[str, str]) -> Path:
    reference = request.private_key_path.strip()
    if reference.startswith("env:"):
        variable = reference[4:]
        reference = str(environment.get(variable) or "")
        if not reference:
            raise ValueError("private key path reference is unavailable")
    return _validate_private_key_path(
        Path(reference) if reference else _read_only_secret_path(DEFAULT_PRIVATE_KEY_NAME)
    )


def _release_notes(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("release notes path is unreadable") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-build-release")
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="仅构建便携版和安装器；不会产出可上传的热更新资产",
    )
    parser.add_argument("--version", default="")
    parser.add_argument("--release-revision", type=int, default=0)
    parser.add_argument("--tag", default="")
    parser.add_argument("--repository", default=DEFAULT_RELEASE_REPOSITORY)
    parser.add_argument("--private-key", default="")
    parser.add_argument("--output-root", default=str(RELEASE_ASSETS_ROOT))
    parser.add_argument("--notes", default="")
    return parser


def _run_release_request(
    request: BuildRequest,
    *,
    preflight_error: BaseException | None = None,
) -> int:
    emitter = ReleaseEventEmitter(stream=sys.stdout)
    hooks = _build_pipeline_hooks(request, os.environ.copy(), emitter)
    if preflight_error is not None:
        def reject_request(_request: BuildRequest) -> None:
            raise preflight_error from None

        hooks = replace(hooks, validate_dependencies=reject_request)
    result = run_release_request(request, hooks, emitter, CancellationToken())
    return 0 if result.succeeded else 1


def _run_request_file(request_file: Path) -> int:
    path = Path(request_file)
    request: BuildRequest | None = None
    load_error: BaseException | None = None
    try:
        try:
            request = load_request_file(path)
        except (Exception, SystemExit) as error:
            load_error = error
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            load_error = ValueError("release request file could not be deleted")
    if load_error is not None:
        return _run_controlled_preflight_failure(load_error)
    if request is None:
        return _run_controlled_preflight_failure(
            ValueError("release request file could not be loaded")
        )
    return _run_release_request(request)


def _build_dry_run_request(*, version: str, build_only: bool) -> BuildRequest:
    version = normalize_version(version)
    return BuildRequest(
        target_version=version,
        remote=RemoteReleaseInfo.available(version),
        apply_version=False,
        build_portable=build_only,
        build_installer=build_only,
        run_smoke_tests=False,
        dry_run=True,
        same_release_repair=False,
        offline_debug=False,
        generate_manifest_key=False,
        rotate_trust_anchor=False,
        sign_manifest=False,
        commit_version_changes=False,
        push_main=False,
        create_or_reuse_tag=False,
        create_or_update_release=False,
        upload_release_assets=False,
        upload_public_key=False,
        verify_remote_assets=False,
    )


def _run_controlled_preflight_failure(error: BaseException) -> int:
    return _run_release_request(
        _build_dry_run_request(version="0.0.0", build_only=False),
        preflight_error=error,
    )


def _run_dry_run_request(*, version: str, build_only: bool) -> int:
    try:
        request = _build_dry_run_request(version=version, build_only=build_only)
    except ValueError as error:
        return _run_controlled_preflight_failure(error)
    return _run_release_request(request)


def _launch_panel() -> int:
    from release_tool.panel import launch_release_builder_panel

    return launch_release_builder_panel()


def build_script_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--request-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", default="")
    parser.add_argument("--build-only", action="store_true")
    return parser


def script_main(argv: list[str]) -> int:
    raw = list(argv)
    if "--gui" in raw or not raw:
        return _launch_panel()
    parser = build_script_parser()
    args, unknown = parser.parse_known_args(raw)
    if args.request_file:
        if (
            unknown
            or args.dry_run
            or args.build_only
            or any(
                token == "--version" or token.startswith("--version=")
                for token in raw
            )
        ):
            parser.error("unsupported arguments for --request-file")
        return _run_request_file(Path(args.request_file))
    if args.dry_run:
        if unknown:
            parser.error("unsupported arguments for --dry-run")
        return _run_dry_run_request(
            version=args.version or read_project_version(PROJECT_ROOT),
            build_only=bool(args.build_only),
        )
    legacy_argv = [token for token in raw if token != "--headless"]
    return main(legacy_argv)


def main(argv: list[str] | None = None) -> int:
    return _run_headless_legacy([] if argv is None else argv)


def _run_headless_legacy(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    package_version, _installer = _project_release_metadata(
        release_revision=args.release_revision
    )
    version = normalize_version(args.version or package_version)
    tag = str(args.tag or format_release_tag(version, args.release_revision)).strip()
    _validate_release_identity(
        package_version=package_version,
        version=version,
        release_revision=args.release_revision,
        tag=tag,
    )

    if args.build_only:
        with _release_build_lock(PROJECT_ROOT) as lock_token:
            _build_binaries(
                PROJECT_ROOT,
                lock_token=lock_token,
                lock_root=PROJECT_ROOT,
                enforce_source_immutability=False,
                release_revision=args.release_revision,
            )
        print("仅构建模式完成；未生成 latest.json / latest.json.sig，不得作为热更新发布。")
        return 0

    private_key = _validate_private_key_path(
        Path(args.private_key) if args.private_key else _default_private_key_path()
    )
    repository = _validate_repository(args.repository)
    output_root = Path(args.output_root)
    destination = output_root.resolve() / tag
    if destination.exists():
        raise SystemExit(f"发布资产目录已存在，拒绝覆盖：{destination}")

    source_commit = _validate_git_release_state(tag)
    with _release_build_lock(PROJECT_ROOT) as lock_token:
        if _validate_git_release_state(tag) != source_commit:
            raise SystemExit("等待构建锁期间 HEAD 或 release tag 发生变化，拒绝发布")
        with _source_snapshot(source_commit, repository_root=PROJECT_ROOT) as snapshot_root:
            _validate_windows_release_tools(snapshot_root)
            snapshot_version, snapshot_installer = _project_release_metadata(
                snapshot_root,
                args.release_revision,
            )
            _validate_release_identity(
                package_version=snapshot_version,
                version=version,
                release_revision=args.release_revision,
                tag=tag,
            )
            _build_binaries(
                snapshot_root,
                lock_token=lock_token,
                lock_root=PROJECT_ROOT,
                release_revision=args.release_revision,
                source_commit=source_commit,
            )
            if _validate_git_release_state(tag) != source_commit:
                raise SystemExit("构建期间 HEAD 或 release tag 发生变化，拒绝签名发布资产")
            release_dir = _prepare_release_assets(
                installer=snapshot_installer,
                private_key=private_key,
                version=version,
                release_revision=args.release_revision,
                tag=tag,
                source_commit=source_commit,
                repository=repository,
                output_root=output_root,
                notes=args.notes,
                project_root=snapshot_root,
            )
    print(f"可上传热更新资产已原子生成：{release_dir}")
    for path in sorted(release_dir.iterdir()):
        print(path)
    print("必须将目录中的三项资产同时上传到同一个 GitHub Release。")
    return 0

if __name__ == "__main__":
    raise SystemExit(script_main(sys.argv[1:]))
