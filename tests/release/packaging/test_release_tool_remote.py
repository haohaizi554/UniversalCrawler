"""Tests for the bounded read-only GitHub latest-release lookup."""

from __future__ import annotations

import sys
from urllib.error import HTTPError
from unittest.mock import Mock, patch

import pytest

from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool import remote
from release_tool.remote import fetch_latest_release, fetch_release_inventory


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

    assert observed["request"].full_url.endswith(
        "/repos/haohaizi554/UniversalCrawler/releases?per_page=30&page=1"
    )
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


@pytest.mark.parametrize("status_code", (403, 429))
def test_fetch_latest_release_falls_back_to_release_page_when_api_is_limited(
    monkeypatch,
    status_code,
):
    monkeypatch.setattr(
        remote,
        "_open_json",
        Mock(
            side_effect=HTTPError(
                "https://api.github.com/repos/owner/repo/releases/latest",
                status_code,
                "rate limited",
                hdrs=None,
                fp=None,
            )
        ),
    )
    page_lookup = Mock(return_value="v3.6.21")
    monkeypatch.setattr(remote, "_open_latest_release_tag", page_lookup)
    environment = {"HTTPS_PROXY": "http://127.0.0.1:7890"}

    info = fetch_latest_release(
        "haohaizi554/UniversalCrawler",
        environment=environment,
        timeout_seconds=2.5,
    )

    assert info.is_available is True
    assert info.version == "3.6.21"
    page_lookup.assert_called_once_with(
        "haohaizi554",
        "UniversalCrawler",
        environment=environment,
        timeout_seconds=2.5,
    )


def test_fetch_latest_release_reports_both_failures_when_rate_limit_fallback_fails(monkeypatch):
    monkeypatch.setattr(
        remote,
        "_open_json",
        Mock(
            side_effect=HTTPError(
                "https://api.github.com/repos/owner/repo/releases/latest",
                403,
                "rate limited",
                hdrs=None,
                fp=None,
            )
        ),
    )
    monkeypatch.setattr(
        remote,
        "_open_latest_release_tag",
        Mock(side_effect=TimeoutError("release page offline")),
    )

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.is_available is False
    assert "HTTP Error 403" in info.error
    assert "release page offline" in info.error


def test_release_page_tag_parsers_accept_only_the_requested_github_repository():
    expected_url = "https://github.com/haohaizi554/UniversalCrawler/releases/tag/v3.6.21"
    other_url = "https://github.com/other/UniversalCrawler/releases/tag/v9.9.9"
    html = (
        '<a href="/other/UniversalCrawler/releases/tag/v9.9.9">other</a>'
        '<a href="/haohaizi554/UniversalCrawler/releases/tag/v3.6.21">latest</a>'
    )

    assert (
        remote._release_tag_from_url(
            expected_url,
            owner="haohaizi554",
            name="UniversalCrawler",
        )
        == "v3.6.21"
    )
    assert not remote._release_tag_from_url(
        other_url,
        owner="haohaizi554",
        name="UniversalCrawler",
    )
    assert (
        remote._release_tag_from_html(
            html,
            owner="haohaizi554",
            name="UniversalCrawler",
        )
        == "v3.6.21"
    )


def test_fetch_latest_release_downgrades_malformed_remote_payload_to_unknown(monkeypatch):
    monkeypatch.setattr(remote, "_open_json", lambda *_args, **_kwargs: {"tag_name": object()})

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.is_available is False
    assert info.error


def test_fetch_latest_release_collects_public_revisions_and_ignores_non_public_entries(
    monkeypatch,
):
    monkeypatch.setattr(
        remote,
        "_open_json",
        lambda *_args, **_kwargs: [
            {"tag_name": "v3.6.21-r2", "draft": False, "prerelease": False},
            {"tag_name": "v3.6.21-r1", "draft": False, "prerelease": False},
            {"tag_name": "v3.6.21", "draft": False, "prerelease": False},
            {"tag_name": "v9.9.9", "draft": True, "prerelease": False},
            {"tag_name": "v8.8.8", "draft": False, "prerelease": True},
            {"tag_name": "not-a-release", "draft": False, "prerelease": False},
        ],
    )

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={})

    assert info.identity.tag == "v3.6.21-r2"
    assert info.release_tags == ("v3.6.21-r2", "v3.6.21-r1", "v3.6.21")
    assert info.next_revision_for("3.6.21") == 3


def test_release_inventory_resumes_only_an_unpublished_tag_matching_head(monkeypatch, tmp_path):
    monkeypatch.setattr(
        remote,
        "fetch_latest_release",
        lambda *_args, **_kwargs: remote.RemoteReleaseInfo.available("v3.6.21"),
    )
    monkeypatch.setattr(
        remote,
        "_git_release_tag_inventory",
        lambda *_args, **_kwargs: (
            ("v3.6.21-r1", "v3.6.21"),
            ("v3.6.21-r1",),
        ),
    )

    info = fetch_release_inventory(
        "haohaizi554/UniversalCrawler",
        environment={},
        project_root=tmp_path,
    )

    assert info.release_tags == ("v3.6.21",)
    assert info.occupied_tags == ("v3.6.21-r1", "v3.6.21")
    assert info.resumable_tags == ("v3.6.21-r1",)
    assert info.target_revision_for("3.6.21") == 1


def test_tag_inventory_keeps_conflicting_or_old_source_tags_immutable():
    occupied, resumable = remote._merge_release_tag_inventory(
        published_tags=("v3.6.21",),
        head_commit="a" * 40,
        local_tags={"v3.6.21": "0" * 40, "v3.6.21-r1": "b" * 40},
        remote_tags={"v3.6.21": "0" * 40},
    )

    assert occupied == ("v3.6.21-r1", "v3.6.21")
    assert resumable == ()


def test_remote_tag_parser_prefers_peeled_annotated_commit():
    parsed = remote._parse_remote_tag_refs(
        f"{'1' * 40}\trefs/tags/v3.6.21\n"
        f"{'2' * 40}\trefs/tags/v3.6.21^{{}}\n"
        f"{'3' * 40}\trefs/tags/v3.6.21-r1\n"
    )

    assert parsed == {
        "v3.6.21": "2" * 40,
        "v3.6.21-r1": "3" * 40,
    }


@pytest.mark.parametrize("timeout", (0, -1, float("inf"), float("nan")))
def test_fetch_latest_release_rejects_non_finite_or_non_positive_timeouts(monkeypatch, timeout):
    open_json = Mock()
    monkeypatch.setattr(remote, "_open_json", open_json)

    info = fetch_latest_release("haohaizi554/UniversalCrawler", environment={}, timeout_seconds=timeout)

    assert info.is_available is False
    open_json.assert_not_called()


def test_proxy_configuration_uses_only_supplied_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.example:8080")
    monkeypatch.setenv("NO_PROXY", "*")

    assert remote._proxy_settings({}) == {}
    assert remote._proxy_settings({"HTTPS_PROXY": "http://supplied.example:8080"}) == {
        "https": "http://supplied.example:8080"
    }
    assert remote._proxy_settings(
        {"HTTPS_PROXY": "http://supplied.example:8080", "NO_PROXY": "api.github.com"}
    ) == {}


def test_no_proxy_matching_supports_exact_and_suffix_names_only():
    assert remote._matches_no_proxy("api.github.com", "github.com")
    assert remote._matches_no_proxy("api.github.com", ".github.com")
    assert remote._matches_no_proxy("api.github.com", "*")
    assert not remote._matches_no_proxy("api.github.com", "notgithub.com")


def test_open_json_rejects_responses_larger_than_the_bound(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            assert size == remote.MAX_RESPONSE_BYTES + 1
            return b"x" * size

    class Opener:
        def open(self, _request, *, timeout):
            assert timeout == 2
            return Response()

    monkeypatch.setattr(remote, "build_opener", lambda _handler: Opener())

    with pytest.raises(ValueError, match="response exceeds"):
        remote._open_json(
            remote.Request("https://api.github.com/repos/owner/repo/releases/latest"),
            environment={},
            timeout_seconds=2,
        )


def test_open_json_retries_a_transient_proxy_disconnect(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"tag_name":"v3.6.21"}'

    class Opener:
        calls = 0

        def open(self, _request, *, timeout):
            assert timeout == 2
            self.calls += 1
            if self.calls == 1:
                raise ConnectionResetError(10054, "connection forcibly closed")
            return Response()

    opener = Opener()
    monkeypatch.setattr(remote, "build_opener", lambda _handler: opener)

    with patch("time.sleep") as sleep:
        payload = remote._open_json(
            remote.Request("https://api.github.com/repos/owner/repo/releases/latest"),
            environment={},
            timeout_seconds=2,
        )

    assert payload == {"tag_name": "v3.6.21"}
    assert opener.calls == 2
    sleep.assert_called_once_with(1.0)


def test_open_json_does_not_retry_a_rate_limit_response(monkeypatch):
    error = HTTPError(
        "https://api.github.com/repos/owner/repo/releases/latest",
        429,
        "rate limited",
        hdrs=None,
        fp=None,
    )
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(remote, "build_opener", lambda _handler: opener)

    with patch("time.sleep") as sleep, pytest.raises(HTTPError) as caught:
        remote._open_json(
            remote.Request("https://api.github.com/repos/owner/repo/releases/latest"),
            environment={},
            timeout_seconds=2,
        )

    assert caught.value is error
    assert opener.open.call_count == 1
    sleep.assert_not_called()
