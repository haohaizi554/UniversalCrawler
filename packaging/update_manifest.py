"""生成并签名更新发布清单。

本脚本仅供发布机使用。签名覆盖最终写入 ``latest.json`` 的精确 UTF-8 字节，
包括排序、缩进和末尾换行；``latest.json.sig`` 保存这些字节的 Ed25519 签名。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 文档约定以 ``python packaging/update_manifest.py`` 直接启动；此时 Python
# 只会自动加入 packaging 目录，需在导入 app/scripts 前补入项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ``Crypto`` 来自仍在维护的 PyCryptodome 包，而非已废弃的 PyCrypto。
from Crypto.PublicKey import ECC  # noqa: E402  # nosec B413
from Crypto.Signature import eddsa  # noqa: E402  # nosec B413

from app.config.update_trust import UPDATE_PUBLIC_KEY_PEM  # noqa: E402
from app.services.secure_updater import (  # noqa: E402
    APP_ID,
    DEFAULT_CHANNEL,
    DEFAULT_MANIFEST_NAME,
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_SIGNATURE_NAME,
    UpdateManifestVerifier,
)
from scripts.update_bootstrap import default_manifest_private_key_path  # noqa: E402


@dataclass(frozen=True)
class ReleaseAssetSpec:
    key: str
    path: Path
    url: str
    os: str
    arch: str
    installer_type: str


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _asset_payload(spec: ReleaseAssetSpec) -> dict[str, Any]:
    path = Path(spec.path)
    if not path.is_file():
        raise FileNotFoundError(f"release asset does not exist: {path}")
    size = path.stat().st_size
    if size > DEFAULT_MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"release asset exceeds configured update limit ({size} > {DEFAULT_MAX_DOWNLOAD_BYTES}): {path}"
        )
    return {
        "name": path.name,
        "url": str(spec.url),
        "sha256": _sha256_file(path),
        "size": size,
        "installerType": str(spec.installer_type),
        "os": str(spec.os),
        "arch": str(spec.arch),
    }


def build_manifest_payload(
    *,
    version: str,
    tag: str,
    assets: list[ReleaseAssetSpec],
    notes: str = "",
    published_at: str | None = None,
    expires_days: int = 30,
    app_id: str = APP_ID,
    channel: str = DEFAULT_CHANNEL,
    min_client_version: str = "3.0.0",
    mandatory: bool = False,
    trusted_hosts: list[str] | tuple[str, ...] = (),
    source_commit: str = "",
) -> dict[str, Any]:
    if not assets:
        raise ValueError("at least one release asset is required")
    published = _parse_or_now(published_at)
    expires_at = published + timedelta(days=int(expires_days))
    payload: dict[str, Any] = {
        "schema": 1,
        "appId": app_id,
        "channel": channel,
        "version": str(version),
        "tag": str(tag),
        "publishedAt": _format_rfc3339(published),
        "expiresAt": _format_rfc3339(expires_at),
        "minClientVersion": str(min_client_version),
        "mandatory": bool(mandatory),
        "notes": str(notes or ""),
        "assets": {spec.key: _asset_payload(spec) for spec in assets},
    }
    if trusted_hosts:
        payload["trustedHosts"] = [str(host).lower() for host in trusted_hosts if host]
    normalized_commit = str(source_commit or "").strip().lower()
    if normalized_commit:
        if len(normalized_commit) != 40 or any(char not in "0123456789abcdef" for char in normalized_commit):
            raise ValueError("source commit must be a full 40-character Git SHA")
        payload["sourceCommit"] = normalized_commit
    return payload


def write_signed_manifest(
    *,
    output_dir: Path,
    private_key_path: Path,
    version: str,
    tag: str,
    assets: list[ReleaseAssetSpec],
    notes: str = "",
    published_at: str | None = None,
    expires_days: int = 30,
    app_id: str = APP_ID,
    channel: str = DEFAULT_CHANNEL,
    min_client_version: str = "3.0.0",
    mandatory: bool = False,
    trusted_hosts: list[str] | tuple[str, ...] = (),
    source_commit: str = "",
    verify_with_config: bool = True,
) -> tuple[Path, Path]:
    """写入清单、签名并可选地用客户端信任锚回读验证。

    写入顺序固定为清单、签名、验证：序列化后的 ``manifest_bytes`` 先原样写入
    ``latest.json``，随后同一字节串被签名并写入 ``latest.json.sig``。验证失败
    时只删除签名，保留清单供发布诊断；私钥读取或签名失败也可能留下已写入的
    清单。

    本函数不承担发布原子性。发布流水线应在暂存目录调用它，并且仅在成功返回
    后把清单与签名作为一对原子地切换到对外发布位置，避免客户端观察到半套
    文件或跨版本组合。
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payload = build_manifest_payload(
        version=version,
        tag=tag,
        assets=assets,
        notes=notes,
        published_at=published_at,
        expires_days=expires_days,
        app_id=app_id,
        channel=channel,
        min_client_version=min_client_version,
        mandatory=mandatory,
        trusted_hosts=trusted_hosts,
        source_commit=source_commit,
    )
    manifest_path = output / DEFAULT_MANIFEST_NAME
    manifest_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    key = ECC.import_key(Path(private_key_path).read_text(encoding="utf-8"))
    signature = eddsa.new(key, "rfc8032").sign(manifest_bytes)
    signature_path = output / DEFAULT_SIGNATURE_NAME
    signature_path.write_bytes(signature)
    if verify_with_config:
        try:
            _verify_with_configured_public_key(
                manifest_path,
                signature_path,
                app_id=app_id,
                channel=channel,
            )
        except Exception:
            signature_path.unlink(missing_ok=True)
            raise
    return manifest_path, signature_path


def _parse_asset_specs(path: Path) -> list[ReleaseAssetSpec]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("asset spec file must be a JSON array")
    specs: list[ReleaseAssetSpec] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("each asset spec must be an object")
        specs.append(
            ReleaseAssetSpec(
                key=str(item["key"]),
                path=Path(str(item["path"])),
                url=str(item["url"]),
                os=str(item["os"]),
                arch=str(item["arch"]),
                installer_type=str(item["installerType"]),
            )
        )
    return specs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ucrawl-update-manifest")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--private-key", default="")
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--asset-spec", required=True, help="JSON array of release asset specs")
    parser.add_argument("--notes", default="")
    parser.add_argument("--published-at", default="")
    parser.add_argument("--expires-days", type=int, default=30)
    parser.add_argument("--min-client-version", default="3.0.0")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--trusted-host", action="append", default=[])
    parser.add_argument("--source-commit", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    private_key = Path(args.private_key) if args.private_key else default_manifest_private_key_path()
    if not private_key.is_file():
        raise SystemExit(
            "未找到 update manifest 私钥，请先运行: "
            "python scripts/update_bootstrap.py generate-manifest-key"
        )
    manifest_path, signature_path = write_signed_manifest(
        output_dir=Path(args.output_dir),
        private_key_path=private_key,
        version=args.version,
        tag=args.tag,
        assets=_parse_asset_specs(Path(args.asset_spec)),
        notes=args.notes,
        published_at=args.published_at or None,
        expires_days=args.expires_days,
        channel=args.channel,
        min_client_version=args.min_client_version,
        mandatory=args.mandatory,
        trusted_hosts=tuple(args.trusted_host or ()),
        source_commit=args.source_commit,
    )
    print(manifest_path)
    print(signature_path)
    return 0


def _parse_or_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _verify_with_configured_public_key(
    manifest_path: Path,
    signature_path: Path,
    *,
    app_id: str,
    channel: str,
) -> None:
    """使用与客户端相同的公开信任锚验证发布输出，防止发布端与消费端规则漂移。"""

    if not str(UPDATE_PUBLIC_KEY_PEM or "").strip():
        raise RuntimeError(
            "UPDATE_PUBLIC_KEY_PEM is empty; run "
            "python scripts/update_bootstrap.py generate-manifest-key --write-public-key-to-config"
        )
    UpdateManifestVerifier(public_key_pem=UPDATE_PUBLIC_KEY_PEM, app_id=app_id, channel=channel).load_verified(
        manifest_path,
        signature_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
