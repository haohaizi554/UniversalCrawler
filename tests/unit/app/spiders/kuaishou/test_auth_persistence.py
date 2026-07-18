from __future__ import annotations

from unittest.mock import ANY, Mock, patch

from app.services.auth_service import AuthService
from app.spiders.kuaishou.spider import KuaishouSpider


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.config = {}
    spider.auth_service = Mock(spec=AuthService)
    spider._effective_proxy_server = Mock(return_value=None)
    spider.log = Mock()
    spider.is_running = True
    return spider


def test_kuaishou_persistence_includes_indexed_db_state() -> None:
    spider = _spider()
    context = Mock()
    snapshot = {
        "cookies": [
            {
                "name": "userId",
                "value": "123",
                "domain": ".kuaishou.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    context.storage_state.return_value = snapshot

    assert spider._persist_authenticated_state(context, "ks_auth.json") is True

    context.storage_state.assert_called_once_with(indexed_db=True)
    spider.auth_service.save_json_file.assert_called_once_with("ks_auth.json", snapshot)


def test_kuaishou_manual_login_does_not_save_on_user_cookie_alone() -> None:
    spider = _spider()
    spider._user_cookie_values = Mock(return_value={"uid"})
    spider._login_prompt_visible = Mock(return_value=False)
    spider._is_logged_in = Mock(return_value=False)
    spider._profile_session_valid = Mock(return_value=False)
    spider._persist_authenticated_state = Mock(return_value=True)
    spider.interruptible_page_wait = Mock(return_value=True)

    result = spider._wait_for_manual_login(Mock(), Mock(), "ks_auth.json")

    assert result is False
    assert spider._profile_session_valid.call_count == 120
    spider._persist_authenticated_state.assert_not_called()


def test_kuaishou_profile_endpoint_confirms_server_session() -> None:
    spider = _spider()
    spider._user_agent = Mock(return_value="test-agent")
    policy = Mock()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    response = Mock(ok=True)
    response.json.return_value = {"result": 1}
    page = Mock()
    page.context.cookies.return_value = []
    request_api = Mock()
    isolated = request_api.new_context.return_value
    isolated.get.return_value = response
    spider._profile_request_api = request_api

    assert spider._profile_session_valid(page) is True

    policy.require_public_url.assert_called_once_with(spider.PROFILE_SESSION_URL)
    isolated.get.assert_called_once()


def test_kuaishou_profile_probe_uses_isolated_request_cookie_jar() -> None:
    spider = _spider()
    spider._user_agent = Mock(return_value="test-agent")
    spider._public_domain_policy_engine = Mock(return_value=Mock())
    snapshot = {
        "cookies": [
            {
                "name": "userId",
                "value": "123",
                "domain": ".kuaishou.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    page = Mock()
    page.context.cookies.return_value = snapshot["cookies"]
    shared_response = Mock(ok=True)
    shared_response.json.return_value = {"result": 1}
    page.request.get.return_value = shared_response
    request_api = Mock()
    isolated = request_api.new_context.return_value
    isolated_response = Mock(ok=True)
    isolated_response.json.return_value = {"result": 1}
    isolated.get.return_value = isolated_response
    spider._profile_request_api = request_api

    assert spider._profile_session_valid(page) is True

    page.request.get.assert_not_called()
    request_api.new_context.assert_called_once_with(
        storage_state=snapshot,
        user_agent="test-agent",
        timeout=spider.PROFILE_SESSION_TIMEOUT_MS,
    )
    isolated.get.assert_called_once()
    isolated_response.dispose.assert_called_once()
    isolated.dispose.assert_called_once()


def test_kuaishou_profile_probe_inherits_browser_proxy() -> None:
    spider = _spider()
    spider.config = {"proxy": "http://127.0.0.1:7890"}
    spider._effective_proxy_server.return_value = "http://127.0.0.1:7890"
    spider._user_agent = Mock(return_value="test-agent")
    spider._public_domain_policy_engine = Mock(return_value=Mock())
    request_api = Mock()
    request_api.new_context.return_value.get.return_value = Mock(
        ok=True,
        json=Mock(return_value={"result": 1}),
    )
    spider._profile_request_api = request_api
    page = Mock()
    page.context.cookies.return_value = []

    assert spider._profile_session_valid(page) is True

    request_api.new_context.assert_called_once_with(
        storage_state={"cookies": [], "origins": []},
        user_agent="test-agent",
        timeout=spider.PROFILE_SESSION_TIMEOUT_MS,
        proxy={"server": "http://127.0.0.1:7890"},
    )


def test_kuaishou_persistence_rejects_degraded_authentication_snapshot() -> None:
    spider = _spider()
    spider._loaded_storage_state = {
        "cookies": [
            {
                "name": "userId",
                "value": "123",
                "domain": ".kuaishou.com",
                "path": "/",
            },
            {
                "name": "kuaishou.server.webday7_st",
                "value": "long-lived",
                "domain": "www.kuaishou.com",
                "path": "/",
            },
        ],
        "origins": [],
    }
    context = Mock()
    context.storage_state.return_value = {
        "cookies": [
            {
                "name": "userId",
                "value": "123",
                "domain": ".kuaishou.com",
                "path": "/",
            }
        ],
        "origins": [],
    }

    assert spider._persist_authenticated_state(context, "ks_auth.json") is False

    spider.auth_service.save_json_file.assert_not_called()


def test_kuaishou_persistence_accepts_long_lived_cookie_name_rotation() -> None:
    def state(name: str) -> dict:
        return {
            "cookies": [
                {
                    "name": "userId",
                    "value": "123",
                    "domain": ".kuaishou.com",
                    "path": "/",
                },
                {
                    "name": name,
                    "value": "token",
                    "domain": "www.kuaishou.com",
                    "path": "/",
                },
            ],
            "origins": [],
        }

    assert KuaishouSpider._authenticated_snapshot_is_safe(
        state("kuaishou.server.webday7_st"),
        state("kuaishou.server.web_st"),
    )
    assert KuaishouSpider._authenticated_snapshot_is_safe(
        state("kuaishou.server.web_st"),
        state("kuaishou.server.webday7_st"),
    )


def test_kuaishou_manual_persistence_can_replace_old_token_family() -> None:
    spider = _spider()
    spider._loaded_storage_state = {
        "cookies": [
            {
                "name": "userId",
                "value": "old",
                "domain": ".kuaishou.com",
                "path": "/",
            },
            {
                "name": "kuaishou.server.webday7_st",
                "value": "old-token",
                "domain": "www.kuaishou.com",
                "path": "/",
            },
        ],
        "origins": [],
    }
    current = {
        "cookies": [
            {
                "name": "userId",
                "value": "new",
                "domain": ".kuaishou.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    context = Mock()
    context.storage_state.return_value = current

    assert spider._persist_authenticated_state(
        context,
        "ks_auth.json",
        allow_auth_replacement=True,
    )

    spider.auth_service.save_json_file.assert_called_once_with(
        "ks_auth.json",
        current,
    )


def test_uncertain_manual_login_keeps_existing_token_family_guard() -> None:
    spider = _spider()
    spider.is_running = True
    spider._loaded_storage_state = {
        "cookies": [
            {
                "name": "userId",
                "value": "old",
                "domain": ".kuaishou.com",
                "path": "/",
            },
            {
                "name": "kuaishou.server.webday7_st",
                "value": "old-token",
                "domain": "www.kuaishou.com",
                "path": "/",
            },
        ],
        "origins": [],
    }
    spider._user_cookie_values = Mock(return_value={"new"})
    spider._login_prompt_visible = Mock(return_value=False)
    spider._profile_session_valid = Mock(return_value=None)
    spider._is_logged_in = Mock(return_value=True)
    spider._persist_authenticated_state = Mock(return_value=False)
    spider.interruptible_page_wait = Mock(return_value=True)
    context = Mock()

    assert spider._wait_for_manual_login(Mock(), context, "ks_auth.json") is False

    spider._persist_authenticated_state.assert_called_once_with(
        context,
        "ks_auth.json",
        allow_auth_replacement=False,
    )


def test_manual_login_wait_stops_at_total_deadline() -> None:
    spider = _spider()
    spider.is_running = True
    spider._user_cookie_values = Mock(return_value={"uid"})
    spider._login_prompt_visible = Mock(return_value=False)
    spider._profile_session_valid = Mock(return_value=False)
    spider.interruptible_page_wait = Mock(return_value=True)

    with patch(
        "app.spiders.kuaishou.auth_runtime.time.monotonic",
        side_effect=[0.0, 121.0],
        create=True,
    ):
        assert spider._wait_for_manual_login(Mock(), Mock(), "ks_auth.json") is False

    spider._profile_session_valid.assert_not_called()


def test_kuaishou_profile_endpoint_rejects_logged_out_session() -> None:
    spider = _spider()
    spider._user_agent = Mock(return_value="test-agent")
    spider._public_domain_policy_engine = Mock(return_value=Mock())
    response = Mock(ok=True)
    response.json.return_value = {"result": 109}
    page = Mock()
    page.context.cookies.return_value = []
    request_api = Mock()
    isolated = request_api.new_context.return_value
    isolated.get.return_value = response
    spider._profile_request_api = request_api

    assert spider._profile_session_valid(page) is False


def test_kuaishou_profile_endpoint_does_not_follow_external_redirect() -> None:
    spider = _spider()
    spider._user_agent = Mock(return_value="test-agent")
    policy = Mock()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    response = Mock(
        ok=False,
        status=302,
        headers={"location": "http://127.0.0.1:8080/private"},
    )
    page = Mock()
    snapshot = {"cookies": [], "origins": []}
    page.context.cookies.return_value = []
    request_api = Mock()
    isolated = request_api.new_context.return_value
    isolated.get.return_value = response
    spider._profile_request_api = request_api

    assert spider._profile_session_valid(page) is None

    request_api.new_context.assert_called_once_with(
        storage_state=snapshot,
        user_agent="test-agent",
        timeout=spider.PROFILE_SESSION_TIMEOUT_MS,
    )
    isolated.get.assert_called_once_with(
        spider.PROFILE_SESSION_URL,
        headers={"Referer": "https://www.kuaishou.com/"},
        timeout=spider.PROFILE_SESSION_TIMEOUT_MS,
        fail_on_status_code=False,
        max_redirects=0,
    )
    policy.require_public_url.assert_called_once_with(spider.PROFILE_SESSION_URL)


def test_kuaishou_visible_login_prompt_wins_over_generic_avatar() -> None:
    spider = _spider()
    page = Mock()

    def locator(selector: str):
        visible = selector in {".sidebar-login-button", "[class*='avatar']"}
        item = Mock()
        item.first = item
        item.is_visible.return_value = visible
        return item

    page.locator.side_effect = locator

    assert spider._is_logged_in(page) is False


def test_kuaishou_ensure_login_accepts_server_confirmed_saved_state() -> None:
    spider = _spider()
    spider._goto_with_retry = Mock(return_value=True)
    spider._user_cookie_values = Mock(return_value={"uid"})
    spider._profile_session_valid = Mock(return_value=True)
    spider._is_logged_in = Mock(return_value=False)
    spider._persist_authenticated_state = Mock(return_value=False)
    spider._refresh_logged_in_state = Mock(return_value=False)
    page = Mock()
    context = Mock()

    result = spider._ensure_login(
        page,
        context,
        "ks_auth.json",
        allow_manual_login=False,
    )

    assert result is True
    spider._persist_authenticated_state.assert_called_once_with(context, "ks_auth.json")


def test_kuaishou_uncertain_profile_probe_does_not_overwrite_saved_state() -> None:
    spider = _spider()
    spider._goto_with_retry = Mock(return_value=True)
    spider._user_cookie_values = Mock(return_value={"uid"})
    spider._profile_session_valid = Mock(return_value=None)
    spider._is_logged_in = Mock(return_value=True)
    spider._persist_authenticated_state = Mock(return_value=True)

    assert spider._ensure_login(
        Mock(),
        Mock(),
        "ks_auth.json",
        allow_manual_login=False,
    )

    spider._persist_authenticated_state.assert_not_called()


def test_kuaishou_login_recheck_waits_for_delayed_dom_state() -> None:
    spider = _spider()
    spider._profile_session_valid = Mock(return_value=None)
    spider._is_logged_in = Mock(side_effect=[False, False, True])
    spider.interruptible_page_wait = Mock(return_value=True)

    result = spider._refresh_logged_in_state(
        Mock(),
        "https://www.kuaishou.com/search/video?searchKey=demo",
    )

    assert result == (True, None)
    spider._profile_session_valid.assert_called_once_with(
        ANY,
        timeout_ms=spider.LOGIN_RECHECK_PROFILE_TIMEOUT_MS,
    )
    assert spider.interruptible_page_wait.call_count == 3
