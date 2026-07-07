"""Tests for shared anti-detection runtime helpers."""

import unittest
from unittest.mock import patch

from app.core.anti_detection import build_browser_anti_detection, resolve_user_agent

class AntiDetectionTests(unittest.TestCase):
    def test_build_browser_anti_detection_prefers_runtime_config(self):
        context = build_browser_anti_detection(
            "kuaishou",
            {"ua": "ua-custom", "proxy": "http://127.0.0.1:7890"},
            referer="https://www.kuaishou.com/",
            default_user_agent="ua-default",
            viewport={"width": 1280, "height": 800},
        )

        self.assertEqual(context.source, "kuaishou")
        self.assertEqual(context.user_agent, "ua-custom")
        self.assertEqual(context.proxy_server, "http://127.0.0.1:7890")
        self.assertEqual(
            context.browser_launch_kwargs(),
            {
                "headless": False,
                "proxy": {"server": "http://127.0.0.1:7890"},
                "args": ["--disable-blink-features=AutomationControlled"],
            },
        )
        self.assertEqual(
            context.browser_context_kwargs(),
            {
                "user_agent": "ua-custom",
                "viewport": {"width": 1280, "height": 800},
            },
        )

    def test_request_headers_keep_referer_and_extra_headers(self):
        context = build_browser_anti_detection(
            "missav",
            {"ua": "ua-custom"},
            referer="https://missav.ai/",
            default_user_agent="ua-default",
        )

        self.assertEqual(
            context.request_headers({"X-Test": "1"}),
            {
                "User-Agent": "ua-custom",
                "Referer": "https://missav.ai/",
                "X-Test": "1",
            },
        )

    @patch("app.utils.user_agents.user_agent_rotator.random", return_value="ua-random")
    def test_default_user_agent_uses_fake_useragent_rotation(self, mocked_random):
        user_agent = resolve_user_agent(
            "bilibili",
            {},
            configured_user_agent="ua-default",
            default_user_agent="ua-default",
        )

        self.assertEqual(user_agent, "ua-random")
        mocked_random.assert_called_once_with("ua-default")

    @patch("app.utils.user_agents.user_agent_rotator.random", return_value="ua-random")
    def test_custom_user_agent_is_not_rotated(self, mocked_random):
        user_agent = resolve_user_agent(
            "kuaishou",
            {},
            configured_user_agent="ua-custom",
            default_user_agent="ua-default",
        )

        self.assertEqual(user_agent, "ua-custom")
        mocked_random.assert_not_called()

    @patch("app.utils.user_agents.user_agent_rotator.random", return_value="ua-random")
    def test_random_sentinel_forces_user_agent_rotation(self, mocked_random):
        user_agent = resolve_user_agent(
            "xiaohongshu",
            {"ua": "random"},
            configured_user_agent="ua-custom",
            default_user_agent="ua-default",
        )

        self.assertEqual(user_agent, "ua-random")
        mocked_random.assert_called_once_with("ua-default")

if __name__ == "__main__":
    unittest.main()
