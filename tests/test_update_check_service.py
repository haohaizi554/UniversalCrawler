import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from Crypto.PublicKey import ECC

from app.services.update_check_service import (
    UPDATE_STATUS_AVAILABLE,
    UPDATE_STATUS_CURRENT,
    UPDATE_STATUS_LOCAL_NEWER,
    UpdateCheckError,
    check_for_update,
    check_secure_update,
    compare_versions,
    fetch_latest_release_page_payload,
    fetch_latest_release_payload,
    normalize_version,
)


class _FakeResponse:
    def __init__(self, *, url: str, body: str = "") -> None:
        self._url = url
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, *_args):
        return self._body


class _FakeBytesResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *_args):
        return self._body


def _pyqt6_available() -> bool:
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        return False
    return True


def _qt_app():
    if not _pyqt6_available():
        return None
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class UpdateCheckServiceTests(unittest.TestCase):
    def test_normalize_version_accepts_display_and_tag_values(self):
        self.assertEqual(normalize_version("v3.6.17"), "3.6.17")
        self.assertEqual(normalize_version("UniversalCrawlerPro 3.7.0"), "3.7.0")

    def test_compare_versions_uses_numeric_segments(self):
        self.assertLess(compare_versions("v3.6.17", "v3.6.18"), 0)
        self.assertEqual(compare_versions("3.6.17", "v3.6.17"), 0)
        self.assertGreater(compare_versions("3.7.0", "3.6.99"), 0)

    def test_check_for_update_reports_current_release(self):
        result = check_for_update(
            "v3.6.17",
            fetcher=lambda: {"tag_name": "v3.6.17", "html_url": "https://example.test/release"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_CURRENT)
        self.assertEqual(result.local_version, "3.6.17")
        self.assertEqual(result.latest_version, "3.6.17")

    def test_check_for_update_reports_available_release(self):
        result = check_for_update(
            "v3.6.17",
            fetcher=lambda: {"tag_name": "v3.6.18", "html_url": "https://example.test/release"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)

    def test_check_for_update_reports_local_newer_release(self):
        result = check_for_update(
            "v3.7.0",
            fetcher=lambda: {"tag_name": "v3.6.18"},
        )
        self.assertEqual(result.status, UPDATE_STATUS_LOCAL_NEWER)

    def test_check_for_update_rejects_missing_release_version(self):
        with self.assertRaises(UpdateCheckError):
            check_for_update("v3.6.17", fetcher=lambda: {"html_url": "https://example.test/release"})

    def test_fetch_latest_release_page_payload_reads_redirect_tag(self):
        response = _FakeResponse(url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18")
        with patch("app.services.update_check_service.open_trusted_url", return_value=response):
            payload = fetch_latest_release_page_payload()

        self.assertEqual(payload["tag_name"], "v3.6.18")
        self.assertEqual(payload["html_url"], "https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.18")

    def test_fetch_latest_release_payload_uses_trusted_url_opener(self):
        response = _FakeResponse(
            url="https://api.github.com/repos/haohaizi554/UniversalCrawler/releases/latest",
            body='{"tag_name":"v3.6.18"}',
        )
        with patch("app.services.update_check_service.open_trusted_url", return_value=response) as opener:
            payload = fetch_latest_release_payload()

        self.assertEqual(payload["tag_name"], "v3.6.18")
        self.assertEqual(opener.call_args.kwargs["allowed_hosts"], {"api.github.com"})

    def test_fetch_latest_release_payload_rejects_non_https_source_before_open(self):
        with patch("app.services.update_check_service.open_trusted_url") as urlopen:
            with self.assertRaisesRegex(UpdateCheckError, "trusted HTTPS"):
                fetch_latest_release_payload(api_url="file:///tmp/latest.json")

        urlopen.assert_not_called()

    def test_fetch_latest_release_page_payload_rejects_untrusted_redirect_host(self):
        response = _FakeResponse(url="https://attacker.example/releases/tag/v9.9.9")
        with patch("app.services.update_check_service.open_trusted_url", return_value=response):
            with self.assertRaisesRegex(UpdateCheckError, "trusted HTTPS"):
                fetch_latest_release_page_payload()

    def test_fetch_latest_release_payload_falls_back_when_api_is_forbidden(self):
        forbidden = HTTPError(
            url="https://api.github.com/repos/haohaizi554/UniversalCrawler/releases/latest",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        response = _FakeResponse(url="https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.19")
        with patch("app.services.update_check_service.open_trusted_url", side_effect=[forbidden, response]):
            payload = fetch_latest_release_payload()

        self.assertEqual(payload["tag_name"], "v3.6.19")

    def test_secure_update_requires_configured_public_key(self):
        with self.assertRaises(UpdateCheckError):
            check_secure_update("v3.6.17", public_key_pem="")

    def test_secure_update_reports_available_signed_manifest(self):
        from tempfile import TemporaryDirectory

        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            manifest_path, sig_path, public_pem = _signed_manifest(Path(temp_dir))

            result = check_secure_update(
                "v3.6.17",
                public_key_pem=public_pem,
                manifest_path=manifest_path,
                signature_path=sig_path,
                os_name="windows",
                arch="x64",
                release_url="https://github.com/owner/repo/releases/tag/v3.7.0",
            )

        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)
        self.assertEqual(result.latest_version, "3.7.0")
        self.assertEqual(result.asset_name, "UniversalCrawlerPro_Setup_3.7.0.exe")
        self.assertEqual(result.installer_type, "inno")

    def test_secure_update_returns_verified_candidates_and_honors_selected_version(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import LocalUpdateState, ManifestLocations
        from tests.test_secure_updater import _signed_manifest

        def overrides(version: str) -> dict:
            return {
                "version": version,
                "tag": f"v{version}",
                "notes": f"release {version}",
                "assets": {
                    "windows-x64": {
                        "name": f"UniversalCrawlerPro_Setup_{version}.exe",
                        "url": f"https://github.com/owner/repo/releases/download/v{version}/installer.exe",
                        "sha256": "b" * 64,
                        "size": 2048,
                        "installerType": "inno",
                        "os": "windows",
                        "arch": "x64",
                    }
                },
            }

        key = ECC.generate(curve="Ed25519")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest38, sig38, public_pem = _signed_manifest(
                root / "v3.8.0",
                key=key,
                manifest_name="latest.json",
                overrides=overrides("3.8.0"),
            )
            manifest37, sig37, _public_pem = _signed_manifest(
                root / "v3.7.0",
                key=key,
                manifest_name="latest.json",
                overrides=overrides("3.7.0"),
            )
            blobs = {
                "https://github.com/owner/repo/releases/download/v3.8.0/latest.json": manifest38.read_bytes(),
                "https://github.com/owner/repo/releases/download/v3.8.0/latest.json.sig": sig38.read_bytes(),
                "https://github.com/owner/repo/releases/download/v3.7.0/latest.json": manifest37.read_bytes(),
                "https://github.com/owner/repo/releases/download/v3.7.0/latest.json.sig": sig37.read_bytes(),
            }

            class FakeReleaseClient:
                def fetch_manifest_location_candidates(self, **_kwargs):
                    return (
                        ManifestLocations(
                            manifest_url="https://github.com/owner/repo/releases/download/v3.8.0/latest.json",
                            signature_url="https://github.com/owner/repo/releases/download/v3.8.0/latest.json.sig",
                            release_url="https://github.com/owner/repo/releases/tag/v3.8.0",
                            tag_name="v3.8.0",
                            release_name="Release 3.8.0",
                        ),
                        ManifestLocations(
                            manifest_url="https://github.com/owner/repo/releases/download/v3.7.0/latest.json",
                            signature_url="https://github.com/owner/repo/releases/download/v3.7.0/latest.json.sig",
                            release_url="https://github.com/owner/repo/releases/tag/v3.7.0",
                            tag_name="v3.7.0",
                            release_name="Release 3.7.0",
                        ),
                    )

            def fake_urlopen(request, timeout, **_kwargs):
                return _FakeBytesResponse(blobs[request.full_url])

            with (
                patch("app.services.update_check_service.open_trusted_url", side_effect=fake_urlopen),
                patch("app.services.update_check_service.user_cache_root", return_value=root / "cache"),
            ):
                result = check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    release_client=FakeReleaseClient(),
                    os_name="windows",
                    arch="x64",
                    state=LocalUpdateState(),
                )

        self.assertEqual(result.latest_version, "3.8.0")
        self.assertEqual([candidate.version for candidate in result.candidates], ["3.8.0", "3.7.0"])
        selected = result.for_version("3.7.0")
        self.assertEqual(selected.latest_version, "3.7.0")
        self.assertEqual(selected.asset_name, "UniversalCrawlerPro_Setup_3.7.0.exe")
        self.assertIn("3.7.0", selected.manifest_path)

    def test_secure_update_reuses_cached_candidate_metadata_when_release_list_is_not_modified(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import LocalUpdateState, ManifestLocations
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_metadata = root / "cache" / "updates" / "metadata"
            manifest_path, sig_path, public_pem = _signed_manifest(root / "source")
            cache_metadata.mkdir(parents=True)
            cached_manifest = cache_metadata / "3.7.0.latest.json"
            cached_signature = cache_metadata / "3.7.0.latest.json.sig"
            cached_manifest.write_bytes(manifest_path.read_bytes())
            cached_signature.write_bytes(sig_path.read_bytes())

            class FakeReleaseClient:
                def fetch_manifest_location_candidates(self, **_kwargs):
                    return (ManifestLocations(not_modified=True),)

            with patch("app.services.update_check_service.user_cache_root", return_value=root / "cache"):
                result = check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    release_client=FakeReleaseClient(),
                    os_name="windows",
                    arch="x64",
                    state=LocalUpdateState(),
                )

        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)
        self.assertEqual(result.latest_version, "3.7.0")
        self.assertEqual(result.manifest_path, str(cached_manifest))

    def test_secure_update_reuses_verified_cache_when_release_discovery_fails(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import DownloadError, LocalUpdateState
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_metadata = root / "cache" / "updates" / "metadata"
            manifest_path, sig_path, public_pem = _signed_manifest(root / "source")
            cache_metadata.mkdir(parents=True)
            (cache_metadata / "3.7.0.latest.json").write_bytes(manifest_path.read_bytes())
            (cache_metadata / "3.7.0.latest.json.sig").write_bytes(sig_path.read_bytes())

            class FailingReleaseClient:
                def fetch_manifest_location_candidates(self, **_kwargs):
                    raise DownloadError("GitHub rate limit reached")

            with patch("app.services.update_check_service.user_cache_root", return_value=root / "cache"):
                result = check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    release_client=FailingReleaseClient(),
                    os_name="windows",
                    arch="x64",
                    state=LocalUpdateState(),
                )

        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)
        self.assertEqual(result.latest_version, "3.7.0")

    def test_secure_update_preserves_last_good_cache_when_fresh_signature_download_fails(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import LocalUpdateState, ManifestLocations
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_metadata = root / "cache" / "updates" / "metadata"
            manifest_path, sig_path, public_pem = _signed_manifest(root / "source")
            cache_metadata.mkdir(parents=True)
            cached_manifest = cache_metadata / "3.7.0.latest.json"
            cached_signature = cache_metadata / "3.7.0.latest.json.sig"
            original_manifest = manifest_path.read_bytes()
            original_signature = sig_path.read_bytes()
            cached_manifest.write_bytes(original_manifest)
            cached_signature.write_bytes(original_signature)

            manifest_url = "https://github.com/owner/repo/releases/download/v3.7.0/latest.json"
            signature_url = f"{manifest_url}.sig"

            class FreshReleaseClient:
                def fetch_manifest_location_candidates(self, **_kwargs):
                    return (
                        ManifestLocations(
                            manifest_url=manifest_url,
                            signature_url=signature_url,
                            tag_name="v3.7.0",
                        ),
                    )

            def failing_urlopen(request, timeout, **_kwargs):
                if request.full_url == signature_url:
                    raise HTTPError(signature_url, 503, "unavailable", None, None)
                return _FakeBytesResponse(b'{"incomplete": true}')

            with (
                patch("app.services.update_check_service.user_cache_root", return_value=root / "cache"),
                patch("app.services.update_check_service.open_trusted_url", side_effect=failing_urlopen),
            ):
                result = check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    release_client=FreshReleaseClient(),
                    os_name="windows",
                    arch="x64",
                    state=LocalUpdateState(),
                )

            self.assertEqual(cached_manifest.read_bytes(), original_manifest)
            self.assertEqual(cached_signature.read_bytes(), original_signature)

        self.assertEqual(result.status, UPDATE_STATUS_AVAILABLE)
        self.assertEqual(result.latest_version, "3.7.0")

    def test_secure_update_uses_readonly_release_status_when_signed_metadata_is_missing_and_local_is_newer(self):
        from app.services.secure_updater import LocalUpdateState, ManifestLocations

        manifest_url = "https://github.com/owner/repo/releases/download/v3.6.14/latest.json"

        class ReleaseClient:
            def fetch_manifest_location_candidates(self, **_kwargs):
                return (
                    ManifestLocations(
                        manifest_url=manifest_url,
                        signature_url=f"{manifest_url}.sig",
                        release_url="https://github.com/owner/repo/releases/tag/v3.6.14",
                        tag_name="v3.6.14",
                    ),
                )

        with (
            patch(
                "app.services.update_check_service.open_trusted_url",
                side_effect=HTTPError(manifest_url, 404, "missing", None, None),
            ),
            patch(
                "app.services.update_check_service.fetch_latest_release_payload",
                return_value={
                    "tag_name": "v3.6.14",
                    "name": "v3.6.14",
                    "html_url": "https://github.com/owner/repo/releases/tag/v3.6.14",
                },
            ),
        ):
            result = check_secure_update(
                "3.6.17",
                public_key_pem="test-public-key",
                release_client=ReleaseClient(),
                os_name="windows",
                arch="x64",
                state=LocalUpdateState(),
            )

        self.assertEqual(result.status, UPDATE_STATUS_LOCAL_NEWER)
        self.assertEqual(result.local_version, "3.6.17")
        self.assertEqual(result.latest_version, "3.6.14")

    def test_secure_update_reports_untrusted_state_when_newer_release_lacks_signed_metadata(self):
        import app.services.update_check_service as update_service
        from app.services.secure_updater import LocalUpdateState, ManifestLocations

        manifest_url = "https://github.com/owner/repo/releases/download/v3.8.0/latest.json"

        class ReleaseClient:
            def fetch_manifest_location_candidates(self, **_kwargs):
                return (
                    ManifestLocations(
                        manifest_url=manifest_url,
                        signature_url=f"{manifest_url}.sig",
                        release_url="https://github.com/owner/repo/releases/tag/v3.8.0",
                        tag_name="v3.8.0",
                    ),
                )

        with (
            patch(
                "app.services.update_check_service.open_trusted_url",
                side_effect=HTTPError(manifest_url, 404, "missing", None, None),
            ),
            patch(
                "app.services.update_check_service.fetch_latest_release_payload",
                return_value={
                    "tag_name": "v3.8.0",
                    "name": "v3.8.0",
                    "html_url": "https://github.com/owner/repo/releases/tag/v3.8.0",
                },
            ),
        ):
            result = check_secure_update(
                "3.6.17",
                public_key_pem="test-public-key",
                release_client=ReleaseClient(),
                os_name="windows",
                arch="x64",
                state=LocalUpdateState(),
            )

        self.assertEqual(result.status, getattr(update_service, "UPDATE_STATUS_UNTRUSTED", "untrusted"))
        self.assertEqual(result.local_version, "3.6.17")
        self.assertEqual(result.latest_version, "3.8.0")
        self.assertEqual(result.manifest_path, "")
        self.assertEqual(result.signature_path, "")

    def test_secure_update_never_downgrades_invalid_signature_to_readonly_release_check(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import LocalUpdateState, ManifestLocations
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path, signature_path, public_pem = _signed_manifest(root / "source")
            signature_path.write_bytes(b"invalid-signature")
            manifest_url = "https://github.com/owner/repo/releases/download/v3.8.0/latest.json"
            signature_url = f"{manifest_url}.sig"
            blobs = {
                manifest_url: manifest_path.read_bytes(),
                signature_url: signature_path.read_bytes(),
            }

            class ReleaseClient:
                def fetch_manifest_location_candidates(self, **_kwargs):
                    return (
                        ManifestLocations(
                            manifest_url=manifest_url,
                            signature_url=signature_url,
                            tag_name="v3.8.0",
                        ),
                    )

            def fake_urlopen(request, timeout, **_kwargs):
                return _FakeBytesResponse(blobs[request.full_url])

            with (
                patch("app.services.update_check_service.user_cache_root", return_value=root / "cache"),
                patch("app.services.update_check_service.open_trusted_url", side_effect=fake_urlopen),
                patch("app.services.update_check_service.fetch_latest_release_payload") as readonly_fetch,
            ):
                with self.assertRaisesRegex(UpdateCheckError, "signature verification failed"):
                    check_secure_update(
                        "3.6.17",
                        public_key_pem=public_pem,
                        release_client=ReleaseClient(),
                        os_name="windows",
                        arch="x64",
                        state=LocalUpdateState(),
                    )

            readonly_fetch.assert_not_called()

    def test_secure_update_rejects_release_head_older_than_last_seen_version(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import LocalUpdateState
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path, sig_path, public_pem = _signed_manifest(root)
            state = LocalUpdateState(last_seen_version="3.8.0")

            with self.assertRaisesRegex(UpdateCheckError, "older than last seen"):
                check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    manifest_path=manifest_path,
                    signature_path=sig_path,
                    os_name="windows",
                    arch="x64",
                    state=state,
                )

        self.assertEqual(state.last_seen_version, "3.8.0")

    def test_secure_update_rejects_manifest_requiring_newer_client(self):
        from tempfile import TemporaryDirectory

        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            manifest_path, sig_path, public_pem = _signed_manifest(
                Path(temp_dir),
                overrides={"minClientVersion": "3.6.18"},
            )

            with self.assertRaises(UpdateCheckError):
                check_secure_update(
                    "v3.6.17",
                    public_key_pem=public_pem,
                    manifest_path=manifest_path,
                    signature_path=sig_path,
                    os_name="windows",
                    arch="x64",
                )

    def test_main_window_update_flow_uses_secure_manifest_path(self):
        source = Path("app/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("check_secure_update", source)
        self.assertIn("_download_verified_update", source)
        self.assertIn("_cancel_update_download", source)
        self.assertIn("entry.updater_helper", source)
        self.assertIn('"--wait-pid"', source)
        self.assertIn('"--manifest"', source)
        self.assertIn('"--signature"', source)
        self.assertNotIn('"--asset-json"', source)
        self.assertIn("shell=False", source)
        self.assertIn("record_skipped_update", source)
        self.assertIn("跳过此版本", source)
        self.assertNotIn("下载和安装稍后接入", source)
        self.assertNotIn("自动下载和安装流程尚未接入", source)

    def test_update_download_rejects_manifest_version_changed_after_selection(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import VerificationError
        from app.services.update_check_service import UpdateCheckResult
        from app.ui.main_window import MainWindow
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            manifest_path, signature_path, public_pem = _signed_manifest(Path(temp_dir))
            result = UpdateCheckResult(
                status=UPDATE_STATUS_AVAILABLE,
                local_version="3.6.17",
                latest_version="3.8.0",
                tag_name="v3.8.0",
                release_name="v3.8.0",
                html_url="https://github.com/owner/repo/releases/tag/v3.8.0",
                manifest_path=str(manifest_path),
                signature_path=str(signature_path),
            )

            with (
                patch("app.ui.main_window.UPDATE_PUBLIC_KEY_PEM", public_pem),
                patch(
                    "app.ui.main_window.Downloader",
                    side_effect=AssertionError("download must not start for a changed manifest"),
                ),
            ):
                with self.assertRaisesRegex(VerificationError, "selected update version"):
                    MainWindow._download_verified_update(result)

    def test_update_download_rechecks_minimum_client_version_before_network(self):
        from tempfile import TemporaryDirectory

        from app.services.secure_updater import VerificationError
        from app.services.update_check_service import UpdateCheckResult
        from app.ui.main_window import MainWindow
        from tests.test_secure_updater import _signed_manifest

        with TemporaryDirectory() as temp_dir:
            manifest_path, signature_path, public_pem = _signed_manifest(
                Path(temp_dir),
                overrides={"minClientVersion": "3.8.0"},
            )
            result = UpdateCheckResult(
                status=UPDATE_STATUS_AVAILABLE,
                local_version="3.6.17",
                latest_version="3.7.0",
                tag_name="v3.7.0",
                release_name="v3.7.0",
                html_url="https://github.com/owner/repo/releases/tag/v3.7.0",
                manifest_path=str(manifest_path),
                signature_path=str(signature_path),
            )

            with (
                patch("app.ui.main_window.UPDATE_PUBLIC_KEY_PEM", public_pem),
                patch(
                    "app.ui.main_window.Downloader",
                    side_effect=AssertionError("download must not start for an incompatible client"),
                ),
            ):
                with self.assertRaisesRegex(VerificationError, "minimum client version"):
                    MainWindow._download_verified_update(result)

    def test_main_window_startup_health_passes_update_staging_directory(self):
        from types import SimpleNamespace

        from app.ui.main_window import MainWindow

        staging_dir = Path("C:/ucrawl-test/update-staging")
        host = SimpleNamespace(
            _current_status_version=lambda: "v3.7.0",
            _display_version=lambda version: version,
        )
        with (
            patch("app.ui.main_window.default_update_staging_dir", return_value=staging_dir, create=True),
            patch("app.ui.main_window.record_startup_update_health") as record_health,
        ):
            MainWindow._record_update_startup_health(host)

        record_health.assert_called_once_with(
            current_version="3.7.0",
            staging_dir=staging_dir,
        )

    def test_update_download_dialog_exposes_cancel_error_retry_and_install_controls(self):
        source = Path("app/ui/dialogs/update_check.py").read_text(encoding="utf-8")

        self.assertIn("class UpdateDownloadDialog", source)
        for text in ("取消下载", "正在取消", "重试", "查看日志", "安装并重启"):
            self.assertIn(text, source)
        self.assertIn("def set_cancelling", source)

    def test_cancel_update_download_enters_non_retryable_cancelling_state(self):
        from app.ui.main_window import MainWindow

        events: list[str] = []

        class CancelEvent:
            def set(self):
                events.append("cancel-event")

        class Dialog:
            def set_cancelling(self):
                events.append("cancelling")

            def set_cancelled(self):
                events.append("cancelled")

        host = type("Host", (), {"append_log": lambda self, _message: None})()
        host.__dict__["_update_download_cancel_event"] = CancelEvent()
        host.__dict__["_update_download_dialog"] = Dialog()

        MainWindow._cancel_update_download(host)

        self.assertEqual(events, ["cancel-event", "cancelling"])

    def test_retry_update_download_waits_until_previous_worker_has_stopped(self):
        from app.services.update_check_service import UpdateCheckResult
        from app.ui.main_window import MainWindow

        events: list[str] = []

        class RunningThread:
            @staticmethod
            def is_alive():
                return True

        host = type(
            "Host",
            (),
            {
                "append_log": lambda self, _message: events.append("log"),
                "_begin_update_download": lambda self, _result: events.append("begin"),
                "_show_update_check_error": lambda self, _message: events.append("error"),
            },
        )()
        host.__dict__["_last_update_result"] = UpdateCheckResult(
            status=UPDATE_STATUS_AVAILABLE,
            local_version="3.6.17",
            latest_version="3.7.0",
            tag_name="v3.7.0",
            release_name="3.7.0",
            html_url="https://example.test/release",
        )
        host.__dict__["_update_download_thread"] = RunningThread()

        MainWindow._retry_update_download(host)

        self.assertEqual(events, ["log"])

    def test_untrusted_update_state_renders_known_versions_without_download_action(self):
        from app.services.update_check_service import UpdateCheckResult
        from app.ui.main_window import MainWindow

        calls: list[tuple] = []
        host = type(
            "Host",
            (),
            {
                "_display_version": staticmethod(lambda version: f"v{str(version).lstrip('vV')}"),
                "_tr": lambda self, text: text,
                "_show_basic_message": lambda self, *args, **kwargs: calls.append(("basic", args, kwargs)),
                "_show_update_available_message": lambda self, *_args: calls.append(("download", (), {})),
                "_show_update_check_error": lambda self, message: calls.append(("generic-error", (message,), {})),
            },
        )()
        result = UpdateCheckResult(
            status="untrusted",
            local_version="3.6.17",
            latest_version="3.8.0",
            tag_name="v3.8.0",
            release_name="Release 3.8.0",
            html_url="https://github.com/owner/repo/releases/tag/v3.8.0",
        )

        MainWindow._show_update_check_result(host, result)

        self.assertEqual(len(calls), 1)
        kind, _args, kwargs = calls[0]
        self.assertEqual(kind, "basic")
        self.assertEqual(kwargs["status"], "error")
        self.assertEqual(kwargs["local_version"], "v3.6.17")
        self.assertEqual(kwargs["latest_version"], "v3.8.0")

    def test_generic_update_error_preserves_known_local_version(self):
        from app.ui.main_window import MainWindow

        calls: list[dict] = []
        host = type(
            "Host",
            (),
            {
                "_display_version": staticmethod(lambda version: f"v{str(version).lstrip('vV')}"),
                "_show_basic_message": lambda self, *_args, **kwargs: calls.append(kwargs),
            },
        )()
        host.__dict__["_last_update_check_local_version"] = "3.6.17"

        MainWindow._show_update_check_error(host, "network unavailable")

        self.assertEqual(calls[0]["local_version"], "v3.6.17")
        self.assertEqual(calls[0]["latest_version"], "")


@unittest.skipUnless(_pyqt6_available(), "PyQt6 is not installed")
class StatusBarUpdateCheckInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()

    def test_version_button_emits_current_version_text(self):
        from app.ui.layout.status_bar import StatusBarWidget

        widget = StatusBarWidget()
        self.addCleanup(widget.deleteLater)
        observed: list[str] = []
        widget.update_check_requested.connect(observed.append)

        widget.render({"version": "v9.9.9"})
        widget.lbl_version.click()

        self.assertEqual(observed, ["v9.9.9"])

    def test_version_button_is_disabled_while_checking(self):
        from app.ui.layout.status_bar import StatusBarWidget

        widget = StatusBarWidget()
        self.addCleanup(widget.deleteLater)

        widget.set_update_checking(True)
        self.assertFalse(widget.lbl_version.isEnabled())
        self.assertTrue(widget.lbl_version.toolTip())
        widget.set_language("en-US")
        self.assertEqual(widget.lbl_version.toolTip(), "Checking for updates...")

        widget.set_update_checking(False)
        self.assertTrue(widget.lbl_version.isEnabled())
        self.assertEqual(widget.lbl_version.toolTip(), "Check for updates")

    def test_update_check_dialog_uses_scoped_theme_styles(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel, QPushButton, QFrame

        from app.ui.dialogs.chromed_dialog import ChromedDialog
        from app.ui.dialogs.update_check import UpdateCheckDialog, UpdateStatusIcon
        from app.ui.layout.window_chrome_controller import FramelessWindowChromeController
        from app.ui.styles import theme_colors

        dialog = UpdateCheckDialog(
            None,
            title="检查更新",
            message="当前版本已经是最新版本。",
            details="当前版本：v3.6.17",
            status=UPDATE_STATUS_CURRENT,
            local_version="v3.6.17",
            latest_version="v3.6.17",
            release_url="https://example.test/release",
        )
        self.addCleanup(dialog.deleteLater)

        colors = theme_colors(dialog._is_dark)
        self.assertIsInstance(dialog, ChromedDialog)
        self.assertIs(dialog.window_title_bar, dialog.chrome_frame.title_bar)
        self.assertIsInstance(dialog._window_chrome_controller, FramelessWindowChromeController)
        self.assertTrue(bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint))
        self.assertIn(colors["bg"], dialog.styleSheet())
        self.assertIn(colors["text"], dialog.styleSheet())
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogTitle"))
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogBody"))
        self.assertIsNotNone(dialog.findChild(QLabel, "DialogStatus"))
        self.assertIsNotNone(dialog.findChild(UpdateStatusIcon, "UpdateStatusIcon"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateStatusBadge"))
        self.assertIsNotNone(dialog.findChild(QFrame, "UpdateVersionPanel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateReleaseLink"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "DialogPrimaryButton"))

    def test_update_check_dialog_uses_current_language(self):
        from PyQt6.QtWidgets import QLabel, QPushButton

        from app.ui.dialogs.update_check import UpdateCheckDialog

        dialog = UpdateCheckDialog(
            None,
            title="检查更新失败",
            message="暂时无法检查最新版本。",
            details="本地版本与 GitHub 最新 Release 一致，无需更新。",
            primary_text="确定",
            status="error",
            local_version="v3.6.17",
            latest_version="v3.6.17",
            language="en-US",
        )
        self.addCleanup(dialog.deleteLater)

        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        buttons = "\n".join(button.text() for button in dialog.findChildren(QPushButton))

        self.assertEqual(dialog.windowTitle(), "Update check failed")
        self.assertIn("Update check failed", labels)
        self.assertIn("Could not check the latest version right now.", labels)
        self.assertIn("Current version", labels)
        self.assertIn("Release version", labels)
        self.assertIn("Check failed", labels)
        self.assertIn("Error details", labels)
        self.assertIn("The local version matches the latest GitHub Release. No update is needed.", labels)
        self.assertIn("OK", buttons)
        for unexpected in ("检查更新失败", "暂时无法", "当前版本", "错误详情", "确定"):
            self.assertNotIn(unexpected, labels + buttons)

    def test_update_check_dialog_translates_local_newer_detail_with_prefix(self):
        from PyQt6.QtWidgets import QLabel

        from app.ui.dialogs.update_check import UpdateCheckDialog

        dialog = UpdateCheckDialog(
            None,
            title="\u68c0\u67e5\u66f4\u65b0",
            message="\u5f53\u524d\u7248\u672c v3.6.17 \u9ad8\u4e8e\u6700\u65b0 Release v3.6.14\u3002",
            details="\u8fd9\u901a\u5e38\u8868\u793a\u4f60\u6b63\u5728\u4f7f\u7528\u672c\u5730\u6784\u5efa\u6216\u9884\u53d1\u5e03\u6784\u5efa\uff0c\u65e0\u9700\u66f4\u65b0\u3002",
            status=UPDATE_STATUS_LOCAL_NEWER,
            local_version="v3.6.17",
            latest_version="v3.6.14",
            language="en-US",
        )
        self.addCleanup(dialog.deleteLater)

        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn(
            "This usually means you are using a local or pre-release build, so no update is needed.",
            labels,
        )
        self.assertNotIn("\u8fd9\u901a\u5e38\u8868\u793a", labels)

    def test_update_check_dialog_exposes_selector_for_multiple_update_candidates(self):
        from PyQt6.QtWidgets import QComboBox, QLabel

        from app.services.update_check_service import UpdateCandidate
        from app.ui.dialogs.update_check import UpdateCheckDialog

        dialog = UpdateCheckDialog(
            None,
            title="\u68c0\u6d4b\u5230\u65b0\u7248\u672c",
            message="\u68c0\u6d4b\u5230\u591a\u4e2a\u53ef\u66f4\u65b0\u7248\u672c\u3002",
            details="\u8bf7\u9009\u62e9\u8981\u5b89\u88c5\u7684\u7248\u672c\u3002",
            status=UPDATE_STATUS_AVAILABLE,
            local_version="v3.6.17",
            latest_version="v3.8.0",
            release_url="https://example.test/releases/v3.8.0",
            candidates=(
                UpdateCandidate(
                    version="3.8.0",
                    tag_name="v3.8.0",
                    release_name="Release 3.8.0",
                    html_url="https://example.test/releases/v3.8.0",
                    notes="notes 3.8.0",
                    asset_name="setup-3.8.0.exe",
                ),
                UpdateCandidate(
                    version="3.7.0",
                    tag_name="v3.7.0",
                    release_name="Release 3.7.0",
                    html_url="https://example.test/releases/v3.7.0",
                    notes="notes 3.7.0",
                    asset_name="setup-3.7.0.exe",
                ),
            ),
        )
        self.addCleanup(dialog.deleteLater)

        combo = dialog.findChild(QComboBox, "UpdateVersionCombo")
        self.assertIsNotNone(combo)
        self.assertEqual(combo.count(), 2)

        combo.setCurrentIndex(1)
        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertEqual(dialog.selected_update_version(), "3.7.0")
        self.assertIn("notes 3.7.0", labels)
