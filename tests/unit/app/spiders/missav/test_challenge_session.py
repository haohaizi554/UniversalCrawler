from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.spiders.missav.challenge_session import (
    ChallengeWaitCancelled,
    ExternalChromeChallengeSession,
)


def _session(tmp_path: Path, **kwargs) -> ExternalChromeChallengeSession:
    return ExternalChromeChallengeSession(
        browser_executable=tmp_path / "chrome.exe",
        profile_dir=tmp_path / "profile",
        poll_interval_seconds=0,
        **kwargs,
    )


def test_external_chrome_launch_keeps_native_browser_fingerprint(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, proxy_server="http://127.0.0.1:7890")
    process = Mock()
    process.poll.return_value = None

    with patch(
        "app.spiders.missav.challenge_session.subprocess.Popen", return_value=process
    ) as popen:
        session.start("https://missav.ai/cn/search/CAWD-377")

    command = popen.call_args.args[0]
    assert "--proxy-server=http://127.0.0.1:7890" in command
    assert any(item.startswith("--remote-debugging-port=") for item in command)
    assert any(item.startswith("--user-data-dir=") for item in command)
    assert not any("AutomationControlled" in item for item in command)
    assert not any(item.startswith("--user-agent=") for item in command)
    assert not any("headless" in item for item in command)


def test_external_chrome_opens_second_url_in_same_profile(tmp_path: Path) -> None:
    session = _session(tmp_path)
    process = Mock()
    process.poll.return_value = None

    with patch(
        "app.spiders.missav.challenge_session.subprocess.Popen", return_value=process
    ) as popen:
        session.start("https://missav.ai/cn/search/CAWD-377")
        session.open_url(
            "https://missav.ai/cn/search/CAWD-377?filters=chinese-subtitle"
        )

    first_command = popen.call_args_list[0].args[0]
    second_command = popen.call_args_list[1].args[0]
    first_profile = next(
        item for item in first_command if item.startswith("--user-data-dir=")
    )
    assert first_profile in second_command
    assert "--new-tab" in second_command


def test_wait_for_ready_page_does_not_attach_during_challenge(tmp_path: Path) -> None:
    session = _session(tmp_path)
    challenge = {
        "id": "challenge",
        "type": "page",
        "url": "https://missav.ai/cn/search/CAWD-377?filters=chinese-subtitle",
        "title": "请稍候…",
    }
    ready = {
        **challenge,
        "id": "ready",
        "title": "cawd-377的搜寻结果 - MissAV | 免费高清AV在线看",
    }
    session._read_targets = Mock(side_effect=[[challenge], [ready]])
    challenge_callback = Mock()

    target = session.wait_for_ready_page(
        challenge["url"],
        timeout_seconds=1,
        cancelled=lambda: False,
        on_challenge=challenge_callback,
    )

    assert target.target_id == "ready"
    challenge_callback.assert_called_once_with("请稍候…")


def test_wait_for_ready_page_honours_task_cancellation(tmp_path: Path) -> None:
    session = _session(tmp_path)

    with pytest.raises(ChallengeWaitCancelled):
        session.wait_for_ready_page(
            "https://missav.ai/cn/search/CAWD-377",
            timeout_seconds=1,
            cancelled=lambda: True,
        )


def test_attach_selects_the_requested_filtered_tab(tmp_path: Path) -> None:
    session = _session(tmp_path)
    base_page = Mock(url="https://missav.ai/cn/search/CAWD-377")
    filtered_page = Mock(
        url="https://missav.ai/cn/search/CAWD-377?filters=chinese-subtitle"
    )
    context = Mock(pages=[base_page, filtered_page])
    browser = Mock(contexts=[context])
    playwright = Mock()
    playwright.chromium.connect_over_cdp.return_value = browser

    attachment = session.attach(
        playwright,
        "https://missav.ai/cn/search/CAWD-377?filters=chinese-subtitle",
    )

    assert attachment.browser is browser
    assert attachment.context is context
    assert attachment.page is filtered_page
    playwright.chromium.connect_over_cdp.assert_called_once_with(
        session.cdp_endpoint,
        timeout=session.CDP_CONNECT_TIMEOUT_MS,
    )
