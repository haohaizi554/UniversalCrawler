"""Generate and sign updater release manifests.

This script is intended for release machines only.  It reads a local Ed25519
private key, computes asset size/SHA-256, writes `latest.json`, and signs the
exact manifest bytes to `latest.json.sig`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from app.services.secure_updater import APP_ID, DEFAULT_CHANNEL, DEFAULT_MANIFEST_NAME, DEFAULT_SIGNATURE_NAME


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
    return {
        "name": path.name,
        "url": str(spec.url),
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
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
) -> tuple[Path, Path]:
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
    )
    manifest_path = output / DEFAULT_MANIFEST_NAME
    manifest_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    key = ECC.import_key(Path(private_key_path).read_text(encoding="utf-8"))
    signature = eddsa.new(key, "rfc8032").sign(manifest_bytes)
    signature_path = output / DEFAULT_SIGNATURE_NAME
    signature_path.write_bytes(signature)
    return manifest_path, signature_path


def _parse_asset_specs(path: Path) -> list[ReleaseAssetSpec]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
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
    parser.add_argument("--private-key", required=True)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path, signature_path = write_signed_manifest(
        output_dir=Path(args.output_dir),
        private_key_path=Path(args.private_key),
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


if __name__ == "__main__":
    raise SystemExit(main())
