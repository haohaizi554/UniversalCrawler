"""Tests for shared anti-detection runtime helpers."""

import unittest

from app.core.anti_detection import build_browser_anti_detection


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


if __name__ == "__main__":
    unittest.main()
