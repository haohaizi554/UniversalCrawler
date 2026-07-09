from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from app.services.secure_updater import (
    AssetSelector,
    DownloadError,
    Downloader,
    GitHubReleaseClient,
    InstallerRunner,
    LocalUpdateState,
    ManifestError,
    PackageVerifier,
    PendingInstall,
    UpdateAsset,
    UpdateManifest,
    UpdateManifestVerifier,
    UpdatePolicy,
    VerificationError,
    VersionPolicy,
    compare_semver,
    record_pending_install,
    record_skipped_update,
    record_startup_update_health,
)


class _BytesResponse:
    def __init__(self, data: bytes, *, headers: dict | None = None) -> None:
        self._data = data
        self._sent = False
        self.headers = headers or {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._data


def _signed_manifest(tmp_path: Path, *, overrides: dict | None = None) -> tuple[Path, Path, str]:
    key = ECC.generate(curve="Ed25519")
    public_pem = key.public_key().export_key(format="PEM")
    payload = {
        "schema": 1,
        "appId": "ucrawl.universalcrawlerpro",
        "channel": "stable",
        "version": "3.7.0",
        "tag": "v3.7.0",
        "publishedAt": "2026-07-09T00:00:00Z",
        "expiresAt": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        "minClientVersion": "3.0.0",
        "mandatory": False,
        "notes": "release notes",
        "assets": {
            "windows-x64": {
                "name": "UniversalCrawlerPro_Setup_3.7.0.exe",
                "url": "https://github.com/owner/repo/releases/download/v3.7.0/installer.exe",
                "sha256": "a" * 64,
                "size": 1024,
                "installerType": "inno",
                "os": "windows",
                "arch": "x64",
            }
        },
    }
    if overrides:
        payload.update(overrides)
    manifest_path = tmp_path / "latest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    signer = eddsa.new(key, "rfc8032")
    signature = signer.sign(manifest_path.read_bytes())
    sig_path = tmp_path / "latest.json.sig"
    sig_path.write_bytes(signature)
    return manifest_path, sig_path, public_pem


def test_semver_compares_numeric_segments_and_prerelease():
    assert compare_semver("1.10.0", "1.9.9") > 0
    assert compare_semver("1.0.0", "1.0.0-rc.1") > 0


def test_version_policy_rejects_stable_prerelease_and_downgrade():
    policy = VersionPolicy(channel="stable", state=LocalUpdateState(last_seen_version="3.8.0"))

    assert not policy.evaluate("3.7.0-rc.1", current_version="3.6.17").allowed
    result = policy.evaluate("3.7.0", current_version="3.6.17")
    assert not result.allowed
    assert "last seen" in result.reason


def test_version_policy_respects_skipped_version_for_automatic_checks():
    policy = VersionPolicy(channel="stable", state=LocalUpdateState(skipped_version="3.7.0"))

    auto = policy.evaluate("3.7.0", current_version="3.6.17", manual=False)
    manual = policy.evaluate("3.7.0", current_version="3.6.17", manual=True)

    assert not auto.allowed
    assert manual.allowed


def test_manifest_signature_failure_is_rejected(tmp_path):
    manifest_path, sig_path, public_pem = _signed_manifest(tmp_path)
    sig_path.write_bytes(b"bad-signature")

    verifier = UpdateManifestVerifier(public_key_pem=public_pem)

    with pytest.raises(ManifestError):
        verifier.load_verified(manifest_path, sig_path)


def test_manifest_rejects_app_id_mismatch_and_expiration(tmp_path):
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    manifest_path, sig_path, public_pem = _signed_manifest(
        tmp_path,
        overrides={"appId": "wrong.app", "expiresAt": expired},
    )
    verifier = UpdateManifestVerifier(public_key_pem=public_pem)

    with pytest.raises(ManifestError):
        verifier.load_verified(manifest_path, sig_path)


def test_asset_selector_requires_exact_platform_and_safe_https_url():
    manifest = UpdateManifest(
        schema=1,
        app_id="ucrawl.universalcrawlerpro",
        channel="stable",
        version="3.7.0",
        tag="v3.7.0",
        published_at="2026-07-09T00:00:00Z",
        expires_at="2026-07-10T00:00:00Z",
        min_client_version="3.0.0",
        mandatory=False,
        notes="",
        assets={
            "linux-x64": UpdateAsset(
                name="bad",
                url="file:///tmp/bad.AppImage",
                sha256="a" * 64,
                size=1,
                installer_type="AppImage",
                os="linux",
                arch="x64",
            )
        },
    )

    with pytest.raises(ManifestError):
        AssetSelector(os_name="windows", arch="x64").select(manifest)


def test_downloader_rejects_size_limit_and_hash_mismatch(tmp_path):
    data = b"not the expected payload"
    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256="0" * 64,
        size=len(data),
        installer_type="inno",
        os="windows",
        arch="x64",
    )

    downloader = Downloader(cache_dir=tmp_path, max_size_bytes=8)
    with pytest.raises(DownloadError):
        downloader.download(asset, opener=lambda _request, timeout: _BytesResponse(data))

    downloader = Downloader(cache_dir=tmp_path, max_size_bytes=1024)
    with pytest.raises(DownloadError):
        downloader.download(asset, opener=lambda _request, timeout: _BytesResponse(data))

    assert not (tmp_path / "installer.exe").exists()


def test_downloader_honors_explicit_trusted_hosts(tmp_path):
    data = b"installer"
    digest = hashlib.sha256(data).hexdigest()
    asset = UpdateAsset(
        name="installer.exe",
        url="https://updates.example.com/downloads/installer.exe",
        sha256=digest,
        size=len(data),
        installer_type="inno",
        os="windows",
        arch="x64",
    )

    with pytest.raises(ManifestError):
        Downloader(cache_dir=tmp_path).download(asset, opener=lambda _request, timeout: _BytesResponse(data))

    target = Downloader(cache_dir=tmp_path, allowed_hosts={"updates.example.com"}).download(
        asset,
        opener=lambda _request, timeout: _BytesResponse(data),
    )

    assert target.read_bytes() == data


def test_downloader_retries_transient_network_errors(tmp_path):
    data = b"installer"
    digest = hashlib.sha256(data).hexdigest()
    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256=digest,
        size=len(data),
        installer_type="inno",
        os="windows",
        arch="x64",
    )
    calls = 0

    def opener(_request, _timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary outage")
        return _BytesResponse(data)

    target = Downloader(cache_dir=tmp_path, retries=1).download(asset, opener=opener)

    assert calls == 2
    assert target.read_bytes() == data


def test_downloader_resumes_existing_partial_file_with_range(tmp_path):
    data = b"0123456789abcdef"
    digest = hashlib.sha256(data).hexdigest()
    partial = tmp_path / "installer.exe.partial"
    partial.write_bytes(data[:5])
    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256=digest,
        size=len(data),
        installer_type="inno",
        os="windows",
        arch="x64",
    )
    seen_ranges: list[str | None] = []

    def opener(request, timeout):
        seen_ranges.append(request.get_header("Range"))
        return _BytesResponse(
            data[5:],
            headers={
                "Content-Length": str(len(data) - 5),
                "Content-Range": f"bytes 5-{len(data) - 1}/{len(data)}",
            },
        )

    target = Downloader(cache_dir=tmp_path).download(asset, opener=opener)

    assert seen_ranges == ["bytes=5-"]
    assert target.read_bytes() == data
    assert not partial.exists()


def test_github_client_handles_304_and_rate_limit(tmp_path):
    cache = tmp_path / "github.json"
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=cache)

    not_modified = client.fetch_manifest_locations(
        opener=lambda request, timeout: (_ for _ in ()).throw(
            client.http_error(request.full_url, 304, "Not Modified")
        )
    )
    assert not_modified.not_modified

    with pytest.raises(DownloadError):
        client.fetch_manifest_locations(
            opener=lambda request, timeout: (_ for _ in ()).throw(
                client.http_error(request.full_url, 429, "rate limited")
            )
        )


def test_github_client_throttles_automatic_checks_but_not_manual(tmp_path):
    cache = tmp_path / "github.json"
    cache.write_text(
        json.dumps(
            {
                "etag": "etag-1",
                "last_modified": "Wed, 09 Jul 2026 00:00:00 GMT",
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "release_url": "https://github.com/owner/repo/releases/tag/v1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=cache)
    calls: list[str] = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise AssertionError("automatic check should be throttled")

    throttled = client.fetch_manifest_locations(opener=opener, manual=False)

    assert throttled.not_modified
    assert calls == []

    def manual_opener(request, timeout):
        calls.append(request.full_url)
        return _BytesResponse(
            json.dumps(
                {
                    "html_url": "https://github.com/owner/repo/releases/tag/v2",
                    "assets": [
                        {
                            "name": "latest.json",
                            "browser_download_url": "https://github.com/owner/repo/releases/download/v2/latest.json",
                        },
                        {
                            "name": "latest.json.sig",
                            "browser_download_url": "https://github.com/owner/repo/releases/download/v2/latest.json.sig",
                        },
                    ],
                }
            ).encode("utf-8"),
            headers={"ETag": "etag-2", "Last-Modified": "Wed, 09 Jul 2026 01:00:00 GMT"},
        )

    fresh = client.fetch_manifest_locations(opener=manual_opener, manual=True)

    assert fresh.release_url.endswith("/v2")
    assert len(calls) == 1


def test_installer_runner_uses_argv_and_records_nonzero_exit(tmp_path):
    installer = tmp_path / "installer.msi"
    installer.write_bytes(b"installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    asset = UpdateAsset(
        name="installer.msi",
        url="https://github.com/owner/repo/releases/download/v/installer.msi",
        sha256=digest,
        size=installer.stat().st_size,
        installer_type="msi",
        os="windows",
        arch="x64",
    )
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(argv, 1603)

    runner = InstallerRunner(
        package_verifier=PackageVerifier(os_name="windows", trusted_publishers=["CN=Test"], verify_func=lambda _p, _a: None),
        run_func=fake_run,
    )

    result = runner.run_verified_installer(installer, asset, version="3.7.0", log_path=tmp_path / "install.log")

    assert result.exit_code == 1603
    assert not result.succeeded
    assert calls[0]["kwargs"]["shell"] is False
    assert calls[0]["argv"][:2] == ["msiexec.exe", "/i"]


def test_macos_verifier_requires_trusted_publisher_allowlist(tmp_path):
    installer = tmp_path / "installer.pkg"
    installer.write_bytes(b"installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    asset = UpdateAsset(
        name="installer.pkg",
        url="https://github.com/owner/repo/releases/download/v/installer.pkg",
        sha256=digest,
        size=installer.stat().st_size,
        installer_type="pkg",
        os="macos",
        arch="arm64",
    )

    with pytest.raises(VerificationError):
        PackageVerifier(os_name="macos", run_func=lambda *a, **k: subprocess.CompletedProcess([], 0)).verify(installer, asset)

    calls: list[dict] = []

    def fake_macos_run(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout="Developer ID Installer: Test", stderr="")

    verifier = PackageVerifier(
        os_name="macos",
        trusted_publishers=["Developer ID Installer: Test"],
        run_func=fake_macos_run,
    )

    verifier.verify(installer, asset)

    assert calls[0]["argv"][:2] == ["pkgutil", "--check-signature"]
    assert calls[1]["argv"][:5] == ["spctl", "-a", "-vv", "-t", "install"]
    assert all(call["kwargs"]["shell"] is False for call in calls)


def test_pending_install_clears_after_new_version_starts(tmp_path):
    state = LocalUpdateState(pending_install=PendingInstall(version="3.7.0", attempts=1))
    state.record_startup_health(current_version="3.7.0", staging_dir=tmp_path)

    assert state.pending_install is None
    assert state.last_install_error == ""


def test_pending_install_state_persists_and_stops_retry_loop(tmp_path):
    state_path = tmp_path / "state.json"

    record_pending_install(
        version="3.7.0",
        installer_path=tmp_path / "installer.exe",
        log_path=tmp_path / "install.log",
        path=state_path,
    )
    first_start = record_startup_update_health(current_version="3.6.17", path=state_path)
    second_start = record_startup_update_health(current_version="3.6.17", path=state_path)

    assert first_start.pending_install is not None
    assert first_start.pending_install.attempts == 1
    assert second_start.pending_install is None
    assert "installed version did not change" in second_start.last_install_error


def test_record_skipped_update_persists_version(tmp_path):
    state = record_skipped_update("v3.7.0", path=tmp_path / "state.json")

    assert state.skipped_version == "3.7.0"


def test_updater_helper_entry_uses_installer_runner_and_no_shell_strings():
    helper = Path("entry/updater_helper.py")

    assert helper.exists()
    source = helper.read_text(encoding="utf-8")
    assert "InstallerRunner" in source
    assert "restart-argv-json" in source
    assert "shell=True" not in source
    assert "os.system" not in source


def test_update_trust_config_contains_only_public_trust_anchors():
    source = Path("app/config/update_trust.py").read_text(encoding="utf-8")

    assert "PRIVATE KEY" not in source
    assert "token" not in source.lower()
    assert "secret" not in source.lower()
    assert "UPDATE_PUBLIC_KEY_PEM" in source
    assert "UPDATE_TRUSTED_PUBLISHERS" in source
    assert "UPDATE_TRUSTED_THUMBPRINTS" in source


def test_updater_helper_restarts_app_after_success_without_shell(tmp_path, monkeypatch):
    from entry import updater_helper

    asset_json = tmp_path / "asset.json"
    asset_json.write_text(
        json.dumps(
            {
                "name": "installer.msi",
                "url": "https://github.com/owner/repo/releases/download/v/installer.msi",
                "sha256": "a" * 64,
                "size": 1,
                "installerType": "msi",
                "os": "windows",
                "arch": "x64",
            }
        ),
        encoding="utf-8",
    )
    installer = tmp_path / "installer.msi"
    installer.write_bytes(b"x")
    calls: list[dict] = []

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        def run_verified_installer(self, *_args, **_kwargs):
            return SimpleNamespace(exit_code=0, succeeded=True)

    monkeypatch.setattr(updater_helper, "InstallerRunner", FakeRunner)
    monkeypatch.setattr(updater_helper.subprocess, "Popen", lambda argv, **kwargs: calls.append({"argv": argv, "kwargs": kwargs}))

    exit_code = updater_helper.main(
        [
            "--installer",
            str(installer),
            "--asset-json",
            str(asset_json),
            "--version",
            "3.7.0",
            "--log-path",
            str(tmp_path / "install.log"),
            "--restart-argv-json",
            json.dumps(["python", "-m", "entry.gui_entry"]),
        ]
    )

    assert exit_code == 0
    assert calls == [{"argv": ["python", "-m", "entry.gui_entry"], "kwargs": {"shell": False}}]
