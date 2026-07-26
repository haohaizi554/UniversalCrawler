from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.web.controller_config_service import WebControllerConfigService


class WebControllerConfigServiceTests(unittest.TestCase):
    def test_tool_actions_require_mapping_payloads(self) -> None:
        actions = (
            "tool_validate",
            "tool_start",
            "tool_cancel",
            "tool_open_result",
            "tool_clear_history",
            "tool_reload",
            "run_tool",
        )

        for action in actions:
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "payload must be an object"):
                    WebControllerConfigService.authorize_frontend_action_payload(
                        action,
                        [],
                        ("C:/trusted",),
                    )

    def test_tool_actions_validate_minimum_fields_and_types(self) -> None:
        invalid_payloads = (
            ("tool_validate", {"parameters": {}}),
            ("tool_validate", {"tool_id": 7, "parameters": {}}),
            ("tool_start", {"tool_id": "media_health"}),
            ("tool_start", {"tool_id": "media_health", "parameters": []}),
            ("tool_cancel", {"tool_id": "media_health"}),
            ("tool_cancel", {"tool_id": "media_health", "run_id": 7}),
            ("tool_open_result", {"tool_id": "media_health"}),
            ("tool_open_result", {"tool_id": "media_health", "result_id": []}),
            ("tool_clear_history", {}),
            ("tool_reload", {"tool_id": 7}),
            ("run_tool", {}),
            ("run_tool", {"id": 7}),
        )

        for action, payload in invalid_payloads:
            with self.subTest(action=action, payload=payload):
                with self.assertRaises(ValueError):
                    WebControllerConfigService.authorize_frontend_action_payload(
                        action,
                        payload,
                        ("C:/trusted",),
                    )

    def test_tool_actions_accept_current_and_legacy_minimum_payloads(self) -> None:
        valid_payloads = (
            ("tool_validate", {"tool_id": "media_health", "parameters": {}}),
            ("tool_start", {"tool_id": "media_health", "parameters": {}}),
            ("tool_cancel", {"tool_id": "media_health", "run_id": "run-7"}),
            ("tool_open_result", {"tool_id": "media_health", "result_id": "result-9"}),
            ("tool_clear_history", {"tool_id": "media_health"}),
            ("tool_reload", {}),
            ("run_tool", {"id": "metadata_viewer"}),
        )

        for action, payload in valid_payloads:
            with self.subTest(action=action):
                self.assertEqual(
                    WebControllerConfigService.authorize_frontend_action_payload(
                        action,
                        payload,
                        ("C:/trusted",),
                    ),
                    payload,
                )

    def test_client_approved_roots_are_removed_from_frontend_payloads(self) -> None:
        payload = WebControllerConfigService.authorize_frontend_action_payload(
            "tool_start",
            {
                "tool_id": "media_health",
                "parameters": {},
                "_approved_roots": ("C:/attacker",),
            },
            ("C:/trusted",),
        )

        self.assertNotIn("_approved_roots", payload)

    def test_update_config_rejects_save_directory_outside_approved_roots(self) -> None:
        service = WebControllerConfigService()
        with tempfile.TemporaryDirectory() as approved_dir, tempfile.TemporaryDirectory() as outside_dir:
            with patch("app.web.controller_config_service.cfg.set") as mocked_set:
                errors = service.update_config(
                    {"common": {"save_directory": str(Path(outside_dir, "downloads"))}},
                    approved_roots=(approved_dir,),
                )

        self.assertEqual(len(errors), 1)
        self.assertIn("授权", errors[0].error)
        mocked_set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
