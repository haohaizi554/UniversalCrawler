from __future__ import annotations

from unittest.mock import Mock

from app.services.auth_service import AuthService
from app.spiders.kuaishou.spider import KuaishouSpider


def _spider() -> KuaishouSpider:
    spider = KuaishouSpider.__new__(KuaishouSpider)
    spider.auth_service = Mock(spec=AuthService)
    spider.log = Mock()
    spider.is_running = True
    return spider


def test_kuaishou_persistence_includes_indexed_db_state() -> None:
    spider = _spider()
    context = Mock()
    snapshot = {"cookies": [{"name": "userId"}], "origins": []}
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
    policy = Mock()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    response = Mock(ok=True)
    response.json.return_value = {"result": 1}
    page = Mock()
    page.request.get.return_value = response

    assert spider._profile_session_valid(page) is True

    policy.require_public_url.assert_called_once_with(spider.PROFILE_SESSION_URL)
    page.request.get.assert_called_once()


def test_kuaishou_profile_endpoint_rejects_logged_out_session() -> None:
    spider = _spider()
    spider._public_domain_policy_engine = Mock(return_value=Mock())
    response = Mock(ok=True)
    response.json.return_value = {"result": 109}
    page = Mock()
    page.request.get.return_value = response

    assert spider._profile_session_valid(page) is False


def test_kuaishou_profile_endpoint_does_not_follow_external_redirect() -> None:
    spider = _spider()
    policy = Mock()
    spider._public_domain_policy_engine = Mock(return_value=policy)
    response = Mock(
        ok=False,
        status=302,
        headers={"location": "http://127.0.0.1:8080/private"},
    )
    page = Mock()
    page.request.get.return_value = response

    assert spider._profile_session_valid(page) is None

    page.request.get.assert_called_once_with(
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
    spider._persist_authenticated_state = Mock(return_value=True)
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
