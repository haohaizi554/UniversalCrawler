from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.upload_transport import GitHubAssetUploadTransport, UploadTransportError


class _Response:
    status_code = 201

    def json(self):
        return {"state": "uploaded"}

    def close(self) -> None:
        pass


class _Session:
    def __init__(self) -> None:
        self.trust_env = True
        self.request: dict[str, object] = {}

    def post(self, url, **kwargs):
        body = kwargs["data"]
        chunks = []
        while True:
            chunk = body.read(3)
            if not chunk:
                break
            chunks.append(chunk)
        self.request = {"url": url, "body": b"".join(chunks), **kwargs}
        return _Response()


def test_transport_streams_file_with_content_length_progress_and_proxy(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"123456789")
    session = _Session()
    progress: list[tuple[int, int, float]] = []
    ticks = iter((0.0, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0))
    transport = GitHubAssetUploadTransport(
        environment={"HTTPS_PROXY": "http://127.0.0.1:7890"},
        token_provider=lambda: "unit-test-token-value",
        session_factory=lambda: session,
        clock=lambda: next(ticks),
        progress_interval_seconds=0.0,
    )

    transport.upload(
        "https://uploads.github.com/repos/haohaizi554/UniversalCrawler/releases/1/assets{?name,label}",
        asset,
        lambda sent, total, speed: progress.append((sent, total, speed)),
    )

    assert session.trust_env is False
    assert session.request["body"] == b"123456789"
    assert session.request["headers"]["Content-Length"] == "9"
    assert session.request["proxies"] == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert progress[-1][0:2] == (9, 9)
    assert progress[-1][2] > 0


def test_transport_rejects_untrusted_upload_host_before_opening_session(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")
    session_factory = pytest.fail
    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=session_factory,
    )

    with pytest.raises(ValueError, match="trusted GitHub upload URL"):
        transport.upload(
            "https://example.invalid/repos/owner/repo/releases/1/assets",
            asset,
            lambda *_args: None,
        )


def test_cleanup_attempts_response_and_session_without_overriding_upload_failure(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")
    cleanup_calls: list[str] = []

    class FailingResponse(_Response):
        status_code = 422

        def close(self) -> None:
            cleanup_calls.append("response")
            raise RuntimeError("response close failed")

    class FailingSession(_Session):
        def post(self, url, **kwargs):
            self.request = {"url": url, **kwargs}
            return FailingResponse()

        def close(self) -> None:
            cleanup_calls.append("session")
            raise RuntimeError("session close failed")

    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=FailingSession,
    )

    with pytest.raises(UploadTransportError, match="HTTP 422"):
        transport.upload(
            "https://uploads.github.com/repos/owner/repo/releases/1/assets",
            asset,
            lambda *_args: None,
        )

    assert cleanup_calls == ["response", "session"]


def test_cleanup_attempts_both_resources_and_reports_failure_after_success(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")
    cleanup_calls: list[str] = []

    class FailingResponse(_Response):
        def close(self) -> None:
            cleanup_calls.append("response")
            raise RuntimeError("response close failed")

    class FailingSession(_Session):
        def post(self, url, **kwargs):
            self.request = {"url": url, **kwargs}
            return FailingResponse()

        def close(self) -> None:
            cleanup_calls.append("session")
            raise RuntimeError("session close failed")

    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=FailingSession,
    )

    with pytest.raises(UploadTransportError, match="cleanup failed"):
        transport.upload(
            "https://uploads.github.com/repos/owner/repo/releases/1/assets",
            asset,
            lambda *_args: None,
        )

    assert cleanup_calls == ["response", "session"]


def test_session_is_closed_when_initial_progress_callback_fails(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")
    cleanup_calls: list[str] = []

    class TrackingSession(_Session):
        def close(self) -> None:
            cleanup_calls.append("session")

    def fail_progress(*_args) -> None:
        raise RuntimeError("progress callback failed")

    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=TrackingSession,
    )

    with pytest.raises(RuntimeError, match="progress callback failed"):
        transport.upload(
            "https://uploads.github.com/repos/owner/repo/releases/1/assets",
            asset,
            fail_progress,
        )

    assert cleanup_calls == ["session"]


def test_cleanup_baseexception_attaches_fixed_note_without_replacing_primary(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")
    primary = RuntimeError("upload remains primary")

    class FailingSession(_Session):
        def close(self) -> None:
            raise KeyboardInterrupt("Authorization: Bearer cleanup-secret")

    def fail_progress(*_args) -> None:
        raise primary

    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=FailingSession,
    )

    with pytest.raises(RuntimeError) as caught:
        transport.upload(
            "https://uploads.github.com/repos/owner/repo/releases/1/assets",
            asset,
            fail_progress,
        )

    assert caught.value is primary
    assert getattr(primary, "__notes__", ()) == [
        "upload cleanup failed: release upload resources could not be closed"
    ]
    assert "cleanup-secret" not in repr(primary.__notes__)


def test_hostile_primary_and_cleanup_diagnostics_never_replace_primary(tmp_path):
    asset = tmp_path / "installer.exe"
    asset.write_bytes(b"payload")

    class HostilePrimary(RuntimeError):
        def __str__(self) -> str:
            raise GeneratorExit("primary string blocked")

        def add_note(self, _note: str) -> None:
            raise SystemExit("note blocked")

    class HostileCleanup(KeyboardInterrupt):
        def __str__(self) -> str:
            raise GeneratorExit("cleanup string blocked")

    primary = HostilePrimary()

    class FailingSession(_Session):
        def close(self) -> None:
            raise HostileCleanup()

    def fail_progress(*_args) -> None:
        raise primary

    transport = GitHubAssetUploadTransport(
        environment={},
        token_provider=lambda: "unit-test-token-value",
        session_factory=FailingSession,
    )

    with pytest.raises(HostilePrimary) as caught:
        transport.upload(
            "https://uploads.github.com/repos/owner/repo/releases/1/assets",
            asset,
            fail_progress,
        )

    assert caught.value is primary
