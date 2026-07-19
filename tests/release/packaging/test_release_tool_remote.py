"""Tests for the bounded read-only GitHub latest-release lookup."""

from __future__ import annotations

import sys
from unittest.mock import Mock

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool import remote
from release_tool.remote import fetch_latest_release


def test_fetch_latest_release_normalizes_tag_version(monkeypatch):
    monkeypatch.setattr(
        remote,
        "_open_json",
        lambda *_args, **_kwargs: {
            "tag_name": "v3.6.21",
            "html_url": "https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.21",
        },
    )

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.is_available is True
    assert info.version == "3.6.21"


def test_fetch_latest_release_uses_fixed_headers_timeout_and_proxy_environment(monkeypatch):
    observed = {}

    def open_json(request, *, environment, timeout_seconds):
        observed["request"] = request
        observed["environment"] = environment
        observed["timeout_seconds"] = timeout_seconds
        return {"tag_name": "v3.6.21"}

    monkeypatch.setattr(remote, "_open_json", open_json)
    environment = {"HTTPS_PROXY": "http://proxy.example:8080"}

    fetch_latest_release(
        "haohaizi554/UniversalCrawler",
        environment=environment,
        timeout_seconds=2.5,
    )

    assert observed["request"].full_url.endswith("/repos/haohaizi554/UniversalCrawler/releases/latest")
    assert observed["request"].get_header("User-agent") == remote.GITHUB_API_USER_AGENT
    assert observed["request"].get_header("Accept") == remote.GITHUB_API_ACCEPT
    assert observed["timeout_seconds"] == 2.5
    assert observed["environment"] == environment
    assert observed["environment"] is not environment


def test_fetch_latest_release_returns_unknown_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(remote, "_open_json", Mock(side_effect=TimeoutError("offline")))

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.is_available is False
    assert info.error == "offline"


def test_fetch_latest_release_downgrades_malformed_remote_payload_to_unknown(monkeypatch):
    monkeypatch.setattr(remote, "_open_json", lambda *_args, **_kwargs: {"tag_name": object()})

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.is_available is False
    assert info.error
