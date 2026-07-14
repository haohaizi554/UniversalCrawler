"""Tests for shared anti-detection runtime helpers."""

import unittest
from unittest.mock import Mock, patch

from app.core.anti_detection import build_browser_anti_detection, load_stealth_script, resolve_user_agent

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
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "extra_http_headers": {
                    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                },
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
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "X-Test": "1",
            },
        )

    def test_browser_anti_detection_accepts_locale_and_timezone_overrides(self):
        context = build_browser_anti_detection(
            "xiaohongshu",
            {
                "ua": "ua-custom",
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "accept_language": "en-US,en;q=0.9",
            },
            referer="https://www.xiaohongshu.com/",
            default_user_agent="ua-default",
        )

        kwargs = context.browser_context_kwargs()
        self.assertEqual(kwargs["locale"], "en-US")
        self.assertEqual(kwargs["timezone_id"], "America/New_York")
        self.assertEqual(kwargs["extra_http_headers"], {"Accept-Language": "en-US,en;q=0.9"})

    def test_stealth_script_covers_common_browser_detection_surfaces(self):
        script = load_stealth_script()

        expected_tokens = [
            "navigatorPrototype",
            "webdriver",
            "window.chrome",
            "plugins",
            "languages",
            "permissions",
            "toDataURL",
            "getImageData",
            "WebGLRenderingContext",
            "WebGL2RenderingContext",
            "resolvedOptions",
            "Asia/Shanghai",
        ]
        for token in expected_tokens:
            self.assertIn(token, script)

    def test_stealth_canvas_noise_samples_a_bounded_surface(self):
        script = load_stealth_script()

        self.assertNotIn("Math.min(1, copy.width)", script)
        self.assertNotIn("Math.min(1, copy.height)", script)
        self.assertIn("Math.min(32, copy.width)", script)
        self.assertIn("Math.min(32, copy.height)", script)

    def test_anti_detection_context_applies_stealth_script_to_playwright_context(self):
        browser_context = Mock()
        anti_context = build_browser_anti_detection(
            "douyin",
            {"ua": "ua-custom"},
            referer="https://www.douyin.com/",
            default_user_agent="ua-default",
        )

        anti_context.apply_to_context(browser_context)

        browser_context.add_init_script.assert_called_once_with(load_stealth_script())

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
