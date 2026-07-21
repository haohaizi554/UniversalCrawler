from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from app.services.update_check_service import compare_versions
from app.services.secure_updater import (
    AssetSelector,
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DownloadError,
    Downloader,
    GitHubReleaseClient,
    InstallerRunner,
    LocalUpdateState,
    ManifestError,
    MetadataNotFoundError,
    PackageVerifier,
    PendingInstall,
    SemVer,
    UpdateAsset,
    UpdateManifest,
    UpdateManifestVerifier,
    VerificationError,
    VersionPolicy,
    compare_semver,
    log_update_event,
    record_pending_install,
    record_skipped_update,
    record_startup_update_health,
    validate_asset_url,
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


def _signed_manifest(
    tmp_path: Path,
    *,
    overrides: dict | None = None,
    key=None,
    manifest_name: str = "latest.json",
) -> tuple[Path, Path, str]:
    key = key or ECC.generate(curve="Ed25519")
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / manifest_name
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    signer = eddsa.new(key, "rfc8032")
    signature = signer.sign(manifest_path.read_bytes())
    sig_path = manifest_path.with_name(f"{manifest_path.name}.sig")
    sig_path.write_bytes(signature)
    return manifest_path, sig_path, public_pem


def test_semver_compares_numeric_segments_and_prerelease():
    assert compare_semver("1.10.0", "1.9.9") > 0
    assert compare_semver("1.0.0", "1.0.0-rc.1") > 0


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.beta"),
        ("1.0.0-alpha.beta", "1.0.0-beta"),
        ("1.0.0-beta", "1.0.0-beta.2"),
        ("1.0.0-beta.2", "1.0.0-beta.11"),
        ("1.0.0-beta.11", "1.0.0-rc.1"),
        ("1.0.0-rc.1", "1.0.0"),
    ],
)
def test_semver_follows_standard_prerelease_precedence_table(lower, higher):
    assert compare_semver(lower, higher) == -1
    assert compare_semver(higher, lower) == 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("1.0.0+20130313144700", "1.0.0+exp.sha.5114f85"),
        ("1.0.0-beta.2+build.7", "1.0.0-beta.2+build.99"),
    ],
)
def test_semver_build_metadata_does_not_affect_precedence(left, right):
    assert compare_semver(left, right) == 0


def test_semver_parse_accepts_optional_v_and_preserves_identifiers():
    assert SemVer.parse("v2.10.3-alpha.7+build.9") == SemVer(
        major=2,
        minor=10,
        patch=3,
        prerelease=("alpha", "7"),
        build="build.9",
    )
    assert compare_semver("V2.10.3", "2.10.3") == 0


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "1",
        "1.2",
        "1.2.3.4",
        "1.2.x",
        "1.2.3-",
        "1.2.3+",
    ],
)
def test_semver_parse_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="invalid semver"):
        SemVer.parse(value)


@pytest.mark.parametrize(
    ("local", "latest", "expected"),
    [
        ("3.10", "3.9", 1),
        ("v3.6", "3.6.0", 0),
        ("release-2.7", "v2.10", -1),
    ],
)
def test_compare_versions_uses_numeric_fallback_for_non_semver_versions(
    local, latest, expected
):
    assert compare_versions(local, latest) == expected


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


def test_manifest_accepts_revision_when_tag_matches(tmp_path):
    manifest_path, sig_path, public_pem = _signed_manifest(
        tmp_path,
        overrides={"releaseRevision": 2, "tag": "v3.7.0-r2", "sourceCommit": "a" * 40},
    )

    manifest = UpdateManifestVerifier(public_key_pem=public_pem).load_verified(
        manifest_path,
        sig_path,
    )

    assert manifest.release_revision == 2
    assert manifest.identity.tag == "v3.7.0-r2"
    assert manifest.source_commit == "a" * 40


@pytest.mark.parametrize("revision", (-1, True, "2", 1.5))
def test_manifest_rejects_invalid_release_revision(tmp_path, revision):
    manifest_path, sig_path, public_pem = _signed_manifest(
        tmp_path,
        overrides={"releaseRevision": revision, "tag": "v3.7.0-r2"},
    )

    with pytest.raises(ManifestError, match="revision"):
        UpdateManifestVerifier(public_key_pem=public_pem).load_verified(manifest_path, sig_path)


def test_manifest_rejects_tag_that_does_not_match_revision(tmp_path):
    manifest_path, sig_path, public_pem = _signed_manifest(
        tmp_path,
        overrides={"releaseRevision": 2, "tag": "v3.7.0-r1"},
    )

    with pytest.raises(ManifestError, match="tag"):
        UpdateManifestVerifier(public_key_pem=public_pem).load_verified(manifest_path, sig_path)


def test_legacy_manifest_without_revision_is_initial_release(tmp_path):
    manifest_path, sig_path, public_pem = _signed_manifest(tmp_path)

    manifest = UpdateManifestVerifier(public_key_pem=public_pem).load_verified(
        manifest_path,
        sig_path,
    )

    assert manifest.release_revision == 0


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


def test_default_download_limit_accepts_large_production_installer_metadata():
    assert DEFAULT_MAX_DOWNLOAD_BYTES == 2 * 1024 * 1024 * 1024

    downloader = Downloader(cache_dir=Path("unused-update-cache"))
    assert downloader.max_size_bytes == DEFAULT_MAX_DOWNLOAD_BYTES
    assert downloader.max_size_bytes > 1_035_581_576


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

    def opener(_request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary outage")
        return _BytesResponse(data)

    target = Downloader(cache_dir=tmp_path, retries=1).download(asset, opener=opener)

    assert calls == 2
    assert target.read_bytes() == data


def test_downloader_passes_timeout_as_keyword_for_urlopen_compatibility(tmp_path):
    data = b"installer"
    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        installer_type="inno",
        os="windows",
        arch="x64",
    )
    seen_timeout: list[float] = []

    def opener(_request, *, timeout):
        seen_timeout.append(timeout)
        return _BytesResponse(data)

    target = Downloader(cache_dir=tmp_path, timeout_seconds=4.25).download(asset, opener=opener)

    assert seen_timeout == [4.25]
    assert target.read_bytes() == data


def test_downloader_uses_real_urlopen_against_loopback_http_server(tmp_path):
    data = b"real urlopen installer payload"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asset = UpdateAsset(
            name="installer.exe",
            url=f"http://127.0.0.1:{server.server_port}/installer.exe",
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            installer_type="inno",
            os="windows",
            arch="x64",
        )
        target = Downloader(
            cache_dir=tmp_path,
            timeout_seconds=2.0,
            development_mode=True,
        ).download(asset)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert target.read_bytes() == data


def test_development_mode_only_relaxes_asset_urls_for_local_sources():
    validate_asset_url("http://127.0.0.1:8765/installer.exe", frozenset(), development_mode=True)
    validate_asset_url("file:///C:/tmp/installer.exe", frozenset(), development_mode=True)

    with pytest.raises(ManifestError, match="not trusted"):
        validate_asset_url(
            "https://attacker.example/installer.exe",
            {"github.com"},
            development_mode=True,
        )
    with pytest.raises(ManifestError, match="must use https"):
        validate_asset_url(
            "http://github.com/owner/repo/installer.exe",
            {"github.com"},
            development_mode=True,
        )
    with pytest.raises(ManifestError, match="must use https"):
        validate_asset_url(
            "file://attacker.example/share/installer.exe",
            {"github.com"},
            development_mode=True,
        )


def test_update_event_filters_all_credential_field_names(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "app.services.secure_updater.debug_logger.log",
        lambda **kwargs: captured.update(kwargs),
    )

    log_update_event(
        "UPDATE_TEST",
        "safe message",
        password="password-value",
        api_key="api-key-value",
        credential="credential-value",
        authorization="bearer-value",
        cookie="cookie-value",
        release_version="3.6.17",
    )

    assert captured["details"] == {"release_version": "3.6.17"}


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


def test_github_latest_release_without_signed_assets_reports_metadata_missing(tmp_path):
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=tmp_path / "github.json")

    def opener(_request, *, timeout):
        return _BytesResponse(
            json.dumps(
                {
                    "tag_name": "v3.8.0",
                    "html_url": "https://github.com/owner/repo/releases/tag/v3.8.0",
                    "assets": [{"name": "installer.exe", "browser_download_url": "https://github.com/file"}],
                }
            ).encode("utf-8")
        )

    with pytest.raises(MetadataNotFoundError):
        client.fetch_manifest_locations(opener=opener, manual=True)


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


def test_github_client_lists_multiple_signed_manifest_locations(tmp_path):
    cache = tmp_path / "github.json"
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=cache)
    seen_urls: list[str] = []

    def opener(request, timeout):
        seen_urls.append(request.full_url)
        return _BytesResponse(
            json.dumps(
                [
                    {
                        "tag_name": "v3.8.0",
                        "name": "Release 3.8.0",
                        "html_url": "https://github.com/owner/repo/releases/tag/v3.8.0",
                        "assets": [
                            {
                                "name": "latest.json",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.8.0/latest.json",
                            },
                            {
                                "name": "latest.json.sig",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.8.0/latest.json.sig",
                            },
                        ],
                    },
                    {
                        "tag_name": "v3.7.0",
                        "name": "Release 3.7.0",
                        "html_url": "https://github.com/owner/repo/releases/tag/v3.7.0",
                        "assets": [
                            {
                                "name": "latest.json",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.7.0/latest.json",
                            },
                            {
                                "name": "latest.json.sig",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.7.0/latest.json.sig",
                            },
                        ],
                    },
                ]
            ).encode("utf-8"),
            headers={"ETag": "etag-list", "Last-Modified": "Wed, 09 Jul 2026 02:00:00 GMT"},
        )

    locations = client.fetch_manifest_location_candidates(opener=opener, manual=True, per_page=5)

    assert seen_urls == ["https://api.github.com/repos/owner/repo/releases?per_page=5"]
    assert [item.tag_name for item in locations] == ["v3.8.0", "v3.7.0"]
    assert locations[0].manifest_url.endswith("/v3.8.0/latest.json")
    assert locations[1].signature_url.endswith("/v3.7.0/latest.json.sig")


def test_github_client_passes_timeout_as_keyword_for_urlopen_compatibility(tmp_path):
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=tmp_path / "github.json", timeout=3.5)
    seen_timeout: list[float] = []

    def opener(request, *, timeout):
        seen_timeout.append(timeout)
        return _BytesResponse(
            json.dumps(
                [
                    {
                        "html_url": "https://github.com/owner/repo/releases/tag/v3.8.0",
                        "assets": [
                            {
                                "name": "latest.json",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.8.0/latest.json",
                            },
                            {
                                "name": "latest.json.sig",
                                "browser_download_url": "https://github.com/owner/repo/releases/download/v3.8.0/latest.json.sig",
                            },
                        ],
                    }
                ]
            ).encode("utf-8"),
        )

    client.fetch_manifest_location_candidates(opener=opener, manual=True)

    assert seen_timeout == [3.5]


def test_github_client_falls_back_to_release_atom_when_api_is_rate_limited(tmp_path):
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=tmp_path / "github.json")
    seen_urls: list[str] = []
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <link rel="alternate" type="text/html" href="https://github.com/owner/repo/releases/tag/v3.8.0" />
    <title>Release 3.8.0</title>
  </entry>
  <entry>
    <link rel="alternate" type="text/html" href="https://github.com/owner/repo/releases/tag/v3.7.0" />
    <title>Release 3.7.0</title>
  </entry>
</feed>"""

    def opener(request, *, timeout):
        seen_urls.append(request.full_url)
        if request.full_url.startswith("https://api.github.com/"):
            raise client.http_error(request.full_url, 429, "rate limited")
        return _BytesResponse(atom)

    locations = client.fetch_manifest_location_candidates(opener=opener, manual=True, per_page=2)

    assert seen_urls == [
        "https://api.github.com/repos/owner/repo/releases?per_page=2",
        "https://github.com/owner/repo/releases.atom",
    ]
    assert [item.tag_name for item in locations] == ["v3.8.0", "v3.7.0"]
    assert locations[0].manifest_url == "https://github.com/owner/repo/releases/download/v3.8.0/latest.json"
    assert locations[1].signature_url == "https://github.com/owner/repo/releases/download/v3.7.0/latest.json.sig"


def test_github_client_rejects_oversized_release_atom(tmp_path):
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=tmp_path / "github.json")

    def opener(request, *, timeout):
        if request.full_url.startswith("https://api.github.com/"):
            raise client.http_error(request.full_url, 429, "rate limited")
        return _BytesResponse(b"x" * 2_000_001)

    with pytest.raises(DownloadError, match="release feed is too large"):
        client.fetch_manifest_location_candidates(opener=opener, manual=True)


def test_github_client_rejects_xml_entities_in_release_atom(tmp_path):
    client = GitHubReleaseClient(owner="owner", repo="repo", cache_path=tmp_path / "github.json")
    atom = b"""<?xml version="1.0"?>
<!DOCTYPE feed [<!ENTITY release "v3.8.0">]>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <link rel="alternate" href="https://github.com/owner/repo/releases/tag/v3.8.0" />
    <title>&release;</title>
  </entry>
</feed>"""

    def opener(request, *, timeout):
        if request.full_url.startswith("https://api.github.com/"):
            raise client.http_error(request.full_url, 429, "rate limited")
        return _BytesResponse(atom)

    with pytest.raises(DownloadError, match="unsafe XML"):
        client.fetch_manifest_location_candidates(opener=opener, manual=True)


def test_trusted_redirect_handler_rejects_target_before_following():
    from app.services.secure_updater import TrustedRedirectHandler

    handler = TrustedRedirectHandler({"github.com", "release-assets.githubusercontent.com"})
    request = urllib.request.Request("https://github.com/owner/repo/releases/download/v/app.exe")

    for target in (
        "http://github.com/owner/repo/app.exe",
        "https://127.0.0.1/app.exe",
        "https://attacker.example/app.exe",
    ):
        with pytest.raises(ManifestError):
            handler.redirect_request(request, None, 302, "Found", {}, target)


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


def test_installer_runner_detaches_inno_self_update_with_post_install_handoff(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256=digest,
        size=installer.stat().st_size,
        installer_type="inno",
        os="windows",
        arch="x64",
    )
    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    restart_handoff = tmp_path / "restart.json"
    calls: list[dict] = []
    process = SimpleNamespace(pid=4321)

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return process

    runner = InstallerRunner(
        package_verifier=PackageVerifier(
            os_name="windows",
            trusted_publishers=["CN=Test"],
            verify_func=lambda _p, _a: None,
        ),
        popen_func=fake_popen,
    )

    launched = runner.launch_verified_installer(
        installer,
        asset,
        version="3.7.0",
        log_path=tmp_path / "install.log",
        install_dir=install_dir,
        restart_handoff_path=restart_handoff,
    )

    assert launched is process
    assert calls[0]["kwargs"]["shell"] is False
    assert calls[0]["kwargs"]["close_fds"] is True
    assert f"/DIR={install_dir}" in calls[0]["argv"]
    assert f"/UCrawlRestartHandoff={restart_handoff}" in calls[0]["argv"]


def _windows_asset_for_file(path: Path) -> UpdateAsset:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return UpdateAsset(
        name=path.name,
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256=digest,
        size=path.stat().st_size,
        installer_type="inno",
        os="windows",
        arch="x64",
    )


def _authenticode_run(
    *,
    status: str = "Valid",
    subject: str = "CN=Trusted Publisher",
    sha1: str = "AA BB CC",
    sha256: str = "11:22:33",
):
    def fake_run(argv, **kwargs):
        payload = {
            "Status": status,
            "Subject": subject,
            "Thumbprint": sha1,
            "SHA256Fingerprint": sha256,
        }
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    return fake_run


def test_package_verifier_explicitly_skips_os_signature_after_hash_check(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("Authenticode command must not run when explicitly disabled")

    def unexpected_verify(*_args, **_kwargs):
        raise AssertionError("OS verification hook must not run when explicitly disabled")

    PackageVerifier(
        os_name="windows",
        require_os_signature=False,
        verify_func=unexpected_verify,
        run_func=unexpected_run,
    ).verify(installer, asset)


def test_package_verifier_cannot_skip_hash_when_os_signature_is_disabled(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"tampered")
    asset = replace(_windows_asset_for_file(installer), sha256="0" * 64)

    with pytest.raises(VerificationError, match="hash"):
        PackageVerifier(os_name="windows", require_os_signature=False).verify(installer, asset)


def test_windows_verifier_rejects_publisher_only_allowlist(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_publishers=["CN=Trusted Publisher"],
        run_func=_authenticode_run(),
    )

    with pytest.raises(VerificationError, match="thumbprint"):
        verifier.verify(installer, asset)


def test_windows_verifier_rejects_publisher_match_when_thumbprint_mismatches(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_publishers=["CN=Trusted Publisher"],
        trusted_thumbprints=["FFFF"],
        run_func=_authenticode_run(),
    )

    with pytest.raises(VerificationError, match="thumbprint"):
        verifier.verify(installer, asset)


def test_windows_verifier_rejects_publisher_mismatch_when_thumbprint_matches(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_publishers=["CN=Expected Publisher"],
        trusted_thumbprints=["AABBCC"],
        run_func=_authenticode_run(
            subject="CN=Unexpected Publisher",
            sha1="AA BB CC",
        ),
    )

    with pytest.raises(VerificationError, match="publisher"):
        verifier.verify(installer, asset)


def test_windows_verifier_accepts_normalized_sha1_thumbprint(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_publishers=["CN=Trusted Publisher"],
        trusted_thumbprints=["aa:bb cc"],
        run_func=_authenticode_run(sha1="AA BB CC"),
    )

    verifier.verify(installer, asset)


def test_windows_verifier_accepts_sha256_fingerprint(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_thumbprints=["112233"],
        run_func=_authenticode_run(sha1="AABBCC", sha256="11:22:33"),
    )

    verifier.verify(installer, asset)


def test_windows_verifier_rejects_invalid_authenticode_status(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    asset = _windows_asset_for_file(installer)
    verifier = PackageVerifier(
        os_name="windows",
        trusted_thumbprints=["AABBCC"],
        run_func=_authenticode_run(status="NotSigned"),
    )

    with pytest.raises(VerificationError, match="not valid"):
        verifier.verify(installer, asset)


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


def test_pending_install_requires_matching_revision_before_it_is_healthy(tmp_path):
    state = LocalUpdateState(
        pending_install=PendingInstall(version="3.7.0", release_revision=2, attempts=0)
    )

    state.record_startup_health(
        current_version="3.7.0",
        current_revision=1,
        staging_dir=tmp_path,
    )

    assert state.pending_install is not None
    assert state.pending_install.attempts == 1
    assert "v3.7.0-r2" in state.last_install_error


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


def test_pending_install_retry_limit_cleans_staging_directory(tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "installer.exe").write_bytes(b"stale installer")
    state = LocalUpdateState(
        pending_install=PendingInstall(version="3.7.0", attempts=1),
        install_attempt_limit=2,
    )

    state.record_startup_health(
        current_version="3.6.17",
        staging_dir=staging_dir,
    )

    assert state.pending_install is None
    assert not staging_dir.exists()


def test_record_skipped_update_persists_version(tmp_path):
    state = record_skipped_update("v3.7.0", path=tmp_path / "state.json")

    assert state.skipped_version == "3.7.0"


def test_update_state_persists_revision_fields(tmp_path):
    state_path = tmp_path / "state.json"

    record_pending_install(
        version="3.7.0",
        release_revision=2,
        installer_path=tmp_path / "installer.exe",
        log_path=tmp_path / "install.log",
        path=state_path,
    )
    state = record_skipped_update("3.7.0", release_revision=1, path=state_path)

    assert state.skipped_revision == 1
    assert state.pending_install is not None
    assert state.pending_install.release_revision == 2
    assert LocalUpdateState.load(state_path).pending_install.release_revision == 2


def test_version_policy_orders_same_version_by_revision_and_never_forces_skipped_update():
    state = LocalUpdateState(
        last_seen_version="3.7.0",
        last_seen_revision=1,
        skipped_version="3.7.0",
        skipped_revision=2,
    )
    policy = VersionPolicy(channel="stable", state=state)

    assert not policy.evaluate(
        "3.7.0",
        update_revision=1,
        current_version="3.7.0",
        current_revision=1,
    ).allowed
    skipped = policy.evaluate(
        "3.7.0",
        update_revision=2,
        current_version="3.7.0",
        current_revision=1,
        mandatory=True,
    )
    manual = policy.evaluate(
        "3.7.0",
        update_revision=2,
        current_version="3.7.0",
        current_revision=1,
        manual=True,
        mandatory=True,
    )

    assert not skipped.allowed
    assert skipped.mandatory is False
    assert manual.allowed
    assert manual.mandatory is False


def test_update_state_load_tolerates_unknown_fields_and_invalid_numbers(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_seen_version": "3.8.0",
                "pending_install": {
                    "version": "3.9.0",
                    "attempts": "not-a-number",
                    "installer_path": "installer.exe",
                    "future_field": True,
                },
                "install_attempt_limit": "invalid",
                "future_root_field": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )

    state = LocalUpdateState.load(state_path)

    assert state.last_seen_version == "3.8.0"
    assert state.install_attempt_limit == 2
    assert state.pending_install == PendingInstall(
        version="3.9.0",
        attempts=0,
        installer_path="installer.exe",
        log_path="",
    )


def test_update_state_load_discards_invalid_semver_fields(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_seen_version": "broken",
                "skipped_version": "also-broken",
                "pending_install": {"version": "not-semver", "attempts": -4},
                "install_attempt_limit": 0,
            }
        ),
        encoding="utf-8",
    )

    state = LocalUpdateState.load(state_path)

    assert state.last_seen_version == ""
    assert state.skipped_version == ""
    assert state.pending_install is None
    assert state.install_attempt_limit == 2


def test_update_state_atomic_save_preserves_previous_file_on_replace_failure(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    original = LocalUpdateState(last_seen_version="3.6.17")
    original.save(state_path)
    original_content = state_path.read_text(encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("replace interrupted")

    monkeypatch.setattr("app.services.secure_updater.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace interrupted"):
        LocalUpdateState(last_seen_version="3.7.0").save(state_path)

    assert state_path.read_text(encoding="utf-8") == original_content
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_updater_helper_entry_uses_installer_runner_and_no_shell_strings():
    helper = Path("entry/updater_helper.py")

    assert helper.exists()
    source = helper.read_text(encoding="utf-8")
    assert "InstallerRunner" in source
    assert "UpdateManifestVerifier" in source
    assert '"--manifest"' in source
    assert '"--signature"' in source
    assert "restart-argv-json" in source
    assert "shell=True" not in source
    assert "os.system" not in source


def test_update_trust_config_contains_only_public_trust_anchors():
    source = Path("app/config/update_trust.py").read_text(encoding="utf-8")

    assert "PRIVATE KEY" not in source
    assert "token" not in source.lower()
    assert "secret" not in source.lower()
    assert "UPDATE_PUBLIC_KEY_PEM" in source
    assert "UPDATE_REQUIRE_OS_SIGNATURE" in source
    assert "UPDATE_TRUSTED_PUBLISHERS" in source
    assert "UPDATE_TRUSTED_THUMBPRINTS" in source


def test_update_trust_config_explicitly_disables_os_signature_for_personal_releases():
    from app.config.update_trust import UPDATE_REQUIRE_OS_SIGNATURE

    assert UPDATE_REQUIRE_OS_SIGNATURE is False


def test_update_entrypoints_pass_shared_os_signature_policy():
    gui_source = Path("app/ui/main_window.py").read_text(encoding="utf-8")
    helper_source = Path("entry/updater_helper.py").read_text(encoding="utf-8")

    for source in (gui_source, helper_source):
        assert "UPDATE_REQUIRE_OS_SIGNATURE" in source
        assert "require_os_signature=UPDATE_REQUIRE_OS_SIGNATURE" in source


def test_updater_helper_loads_asset_from_signed_manifest(tmp_path, monkeypatch):
    from entry import updater_helper

    manifest_path, signature_path, public_pem = _signed_manifest(tmp_path)
    monkeypatch.setattr(updater_helper, "UPDATE_PUBLIC_KEY_PEM", public_pem, raising=False)
    loader = getattr(updater_helper, "_load_verified_asset", lambda **_kwargs: None)

    asset = loader(
        manifest_path=manifest_path,
        signature_path=signature_path,
        expected_version="3.7.0",
        os_name="windows",
        arch="x64",
    )

    assert isinstance(asset, UpdateAsset)
    assert asset.name == "UniversalCrawlerPro_Setup_3.7.0.exe"


def test_updater_helper_rejects_manifest_for_another_revision(tmp_path, monkeypatch):
    from entry import updater_helper

    manifest_path, signature_path, public_pem = _signed_manifest(
        tmp_path,
        overrides={"releaseRevision": 2, "tag": "v3.7.0-r2"},
    )
    monkeypatch.setattr(updater_helper, "UPDATE_PUBLIC_KEY_PEM", public_pem)

    with pytest.raises(VerificationError, match="release identity"):
        updater_helper._load_verified_asset(
            manifest_path=manifest_path,
            signature_path=signature_path,
            expected_version="3.7.0",
            expected_revision=1,
            os_name="windows",
            arch="x64",
        )


def test_revision_change_authorization_is_manifest_bound_and_single_use(tmp_path):
    from app.services.update_check_service import _write_revision_authorization
    from entry import updater_helper
    from shared.release_identity import ReleaseIdentity

    manifest = tmp_path / "latest.json"
    manifest.write_bytes(b'{"signed":"manifest"}')
    identity = ReleaseIdentity("3.7.0", 2)
    authorization_path, token = _write_revision_authorization(
        manifest_path=manifest,
        identity=identity,
    )

    updater_helper._consume_revision_authorization(
        authorization_path=authorization_path,
        token=token,
        manifest_path=manifest,
        target_identity=identity,
    )

    assert not authorization_path.exists()
    with pytest.raises(VerificationError, match="authorization"):
        updater_helper._consume_revision_authorization(
            authorization_path=authorization_path,
            token=token,
            manifest_path=manifest,
            target_identity=identity,
        )


def test_revision_change_authorization_rejects_tampered_manifest(tmp_path):
    from app.services.update_check_service import _write_revision_authorization
    from entry import updater_helper
    from shared.release_identity import ReleaseIdentity

    manifest = tmp_path / "latest.json"
    manifest.write_bytes(b'{"signed":"manifest"}')
    identity = ReleaseIdentity("3.7.0", 2)
    authorization_path, token = _write_revision_authorization(
        manifest_path=manifest,
        identity=identity,
    )
    manifest.write_bytes(b'{"signed":"different"}')

    with pytest.raises(VerificationError, match="manifest"):
        updater_helper._consume_revision_authorization(
            authorization_path=authorization_path,
            token=token,
            manifest_path=manifest,
            target_identity=identity,
        )

    assert not authorization_path.exists()


def test_updater_helper_requires_authorization_only_for_non_forward_transition(tmp_path):
    from entry import updater_helper
    from shared.release_identity import ReleaseIdentity

    manifest = tmp_path / "latest.json"
    manifest.write_bytes(b"signed manifest")

    updater_helper._authorize_release_transition(
        current_identity=ReleaseIdentity("3.7.0", 1),
        target_identity=ReleaseIdentity("3.7.0", 2),
        manifest_path=manifest,
        authorization_path=None,
        token="",
    )

    with pytest.raises(VerificationError, match="one-time local authorization"):
        updater_helper._authorize_release_transition(
            current_identity=ReleaseIdentity("3.7.0", 2),
            target_identity=ReleaseIdentity("3.7.0", 2),
            manifest_path=manifest,
            authorization_path=None,
            token="",
        )


def test_updater_helper_rejects_signed_manifest_for_another_version(tmp_path, monkeypatch):
    from entry import updater_helper

    manifest_path, signature_path, public_pem = _signed_manifest(tmp_path)
    monkeypatch.setattr(updater_helper, "UPDATE_PUBLIC_KEY_PEM", public_pem)

    with pytest.raises(VerificationError, match="does not match requested version"):
        updater_helper._load_verified_asset(
            manifest_path=manifest_path,
            signature_path=signature_path,
            expected_version="3.8.0",
            os_name="windows",
            arch="x64",
        )


def test_updater_helper_detaches_installer_and_writes_restart_handoff(tmp_path, monkeypatch):
    from entry import updater_helper

    asset = UpdateAsset(
        name="installer.exe",
        url="https://github.com/owner/repo/releases/download/v/installer.exe",
        sha256="a" * 64,
        size=1,
        installer_type="inno",
        os="windows",
        arch="x64",
    )
    manifest_path = tmp_path / "latest.json"
    signature_path = tmp_path / "latest.json.sig"
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"x")
    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    restart_exe = install_dir / "UniversalCrawlerPro.exe"
    restart_exe.write_bytes(b"exe")
    calls: list[dict] = []

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        def launch_verified_installer(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return SimpleNamespace(pid=4242)

    monkeypatch.setattr(updater_helper, "InstallerRunner", FakeRunner)
    monkeypatch.setattr(updater_helper, "_load_verified_asset", lambda **_kwargs: asset)

    exit_code = updater_helper.main(
        [
            "--installer",
            str(installer),
            "--manifest",
            str(manifest_path),
            "--signature",
            str(signature_path),
            "--version",
            "3.7.0",
            "--log-path",
            str(tmp_path / "install.log"),
            "--install-dir",
            str(install_dir),
            "--restart-argv-json",
            json.dumps([str(restart_exe), "--updated"]),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["args"][:2] == (installer, asset)
    assert calls[0]["kwargs"]["install_dir"] == install_dir.resolve()
    handoff_path = calls[0]["kwargs"]["restart_handoff_path"]
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff["restart_argv"] == [str(restart_exe), "--updated"]
    assert handoff["install_dir"] == str(install_dir.resolve())
    assert handoff["version"] == "3.7.0"


def test_updater_helper_post_install_restarts_validated_installed_app(tmp_path, monkeypatch):
    from entry import updater_helper

    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    helper_exe = install_dir / "updater_helper.exe"
    restart_exe = install_dir / "UniversalCrawlerPro.exe"
    helper_exe.write_bytes(b"helper")
    restart_exe.write_bytes(b"app")
    handoff_path = tmp_path / "restart.json"
    handoff_path.write_text(
        json.dumps(
            {
                "restart_argv": [str(restart_exe), "--updated"],
                "install_dir": str(install_dir),
                "version": "3.7.0",
                "log_path": str(tmp_path / "install.log"),
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []
    monkeypatch.setattr(updater_helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_helper.sys, "executable", str(helper_exe))
    monkeypatch.setattr(
        updater_helper.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append({"argv": argv, "kwargs": kwargs}),
    )

    exit_code = updater_helper.main(
        [
            "--complete-install",
            "--restart-handoff",
            str(handoff_path),
        ]
    )

    assert exit_code == 0
    assert not handoff_path.exists()
    assert calls[0]["argv"] == [str(restart_exe), "--updated"]
    assert calls[0]["kwargs"]["shell"] is False
    assert calls[0]["kwargs"]["cwd"] == str(install_dir.resolve())


def test_updater_helper_post_install_restart_survives_telemetry_failure(tmp_path, monkeypatch):
    from entry import updater_helper

    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    helper_exe = install_dir / "updater_helper.exe"
    restart_exe = install_dir / "UniversalCrawlerPro.exe"
    helper_exe.write_bytes(b"helper")
    restart_exe.write_bytes(b"app")
    log_path = tmp_path / "install.log"
    handoff_path = tmp_path / "restart.json"
    handoff_path.write_text(
        json.dumps(
            {
                "restart_argv": [str(restart_exe)],
                "install_dir": str(install_dir),
                "version": "3.7.0",
                "log_path": str(log_path),
            }
        ),
        encoding="utf-8",
    )
    launches: list[list[str]] = []
    monkeypatch.setattr(updater_helper.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_helper.sys, "executable", str(helper_exe))
    monkeypatch.setattr(
        updater_helper,
        "log_update_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("logger unavailable")),
    )
    monkeypatch.setattr(
        updater_helper.subprocess,
        "Popen",
        lambda argv, **_kwargs: launches.append(argv),
    )

    exit_code = updater_helper.main(
        [
            "--complete-install",
            "--restart-handoff",
            str(handoff_path),
        ]
    )

    assert exit_code == 0
    assert launches == [[str(restart_exe)]]
    assert not handoff_path.exists()


def test_updater_helper_persists_windowed_failure_when_telemetry_is_unavailable(tmp_path, monkeypatch):
    from entry import updater_helper

    log_path = tmp_path / "install.log"
    monkeypatch.setattr(
        updater_helper,
        "log_update_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("logger unavailable")),
    )

    exit_code = updater_helper.main(["--log-path", str(log_path)])

    assert exit_code == 1
    assert "updater helper failed" in log_path.read_text(encoding="utf-8")
    assert "missing updater helper arguments" in log_path.read_text(encoding="utf-8")


def test_updater_helper_waits_for_parent_before_running_installer(tmp_path, monkeypatch):
    from entry import updater_helper

    asset = UpdateAsset(
        name="installer.msi",
        url="https://github.com/owner/repo/releases/download/v/installer.msi",
        sha256="a" * 64,
        size=1,
        installer_type="msi",
        os="windows",
        arch="x64",
    )
    manifest_path = tmp_path / "latest.json"
    signature_path = tmp_path / "latest.json.sig"
    installer = tmp_path / "installer.msi"
    installer.write_bytes(b"x")
    events: list[tuple[str, int | None]] = []

    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        def launch_verified_installer(self, *_args, **_kwargs):
            events.append(("install", None))
            return SimpleNamespace(pid=4243)

    monkeypatch.setattr(updater_helper, "InstallerRunner", FakeRunner)
    monkeypatch.setattr(updater_helper, "_load_verified_asset", lambda **_kwargs: asset)
    monkeypatch.setattr(updater_helper, "_wait_for_process_exit", lambda pid: events.append(("wait", pid)))

    exit_code = updater_helper.main(
        [
            "--installer",
            str(installer),
            "--manifest",
            str(manifest_path),
            "--signature",
            str(signature_path),
            "--version",
            "3.7.0",
            "--log-path",
            str(tmp_path / "install.log"),
            "--install-dir",
            str(tmp_path),
            "--wait-pid",
            "4242",
        ]
    )

    assert exit_code == 0
    assert events == [("wait", 4242), ("install", None)]
